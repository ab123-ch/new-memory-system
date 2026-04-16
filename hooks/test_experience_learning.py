#!/usr/bin/env python3
"""
经验学习 Hook 测试脚本

测试 LLM 增强的经验提取功能
"""

import sys
import os
import asyncio
from pathlib import Path
from datetime import datetime

# 添加项目路径
PROJECT_PATH = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_PATH))

# 导入测试模块
from hooks.experience_learning import (
    ExperienceLearningLogger,
    LLMExperienceAnalyzer,
    ExperienceFileManager,
    run_experience_learning_with_llm,
    MEMORY_DATA_PATH
)


def test_logger():
    """测试日志记录器"""
    print("\n" + "="*60)
    print("测试 1: ExperienceLearningLogger")
    print("="*60)

    logger = ExperienceLearningLogger(MEMORY_DATA_PATH)
    logger.start_session()

    logger.info("这是一条测试信息")
    logger.success("这是一条成功信息")
    logger.warn("这是一条警告信息")
    logger.error("这是一条错误信息")

    logger.log_experience_detected(
        exp_type="纠正反馈",
        confidence=0.85,
        reason="用户指出了代码错误"
    )

    logger.log_llm_analysis(
        summary="用户纠正了变量命名规范，应使用 snake_case 而非 camelCase",
        key_points=["Python 变量使用 snake_case", "类名使用 PascalCase"],
        tags=["python", "命名规范", "代码风格"]
    )

    logger.end_session()

    # 检查日志文件
    log_file = logger.log_file
    if log_file.exists():
        print(f"✅ 日志文件已创建: {log_file}")
        print(f"   文件大小: {log_file.stat().st_size} bytes")
    else:
        print(f"❌ 日志文件未创建")

    return logger


def test_llm_analyzer():
    """测试 LLM 分析器"""
    print("\n" + "="*60)
    print("测试 2: LLMExperienceAnalyzer")
    print("="*60)

    # 创建临时日志
    logger = ExperienceLearningLogger(MEMORY_DATA_PATH)

    analyzer = LLMExperienceAnalyzer(logger)

    # 测试用例
    test_cases = [
        {
            "user_message": "你的代码有问题，变量名应该用 snake_case 而不是 camelCase，Python 的规范是这样的",
            "assistant_message": "好的，我明白了。Python 变量命名应该使用 snake_case 格式，比如 user_name 而不是 userName。感谢你的指正，我会注意这个规范。",
            "experience_type": "correction"
        },
        {
            "user_message": "建议你在处理大文件时使用生成器而不是列表，这样可以节省内存",
            "assistant_message": "感谢建议！使用生成器确实可以更高效地处理大文件。我会考虑使用 yield 或者生成器表达式来优化内存使用。",
            "experience_type": "suggestion"
        }
    ]

    async def run_tests():
        results = []
        for i, case in enumerate(test_cases, 1):
            print(f"\n--- 测试用例 {i} ---")
            print(f"用户消息: {case['user_message'][:50]}...")

            try:
                result = await analyzer.analyze(
                    user_message=case["user_message"],
                    assistant_message=case["assistant_message"],
                    experience_type=case["experience_type"]
                )

                print(f"✅ LLM 分析成功")
                print(f"   总结: {result.get('summary', 'N/A')}")
                print(f"   关键要点: {result.get('key_points', [])}")
                print(f"   标签: {result.get('tags', [])}")
                print(f"   重要性: {result.get('importance', 0):.0%}")
                print(f"   置信度: {result.get('confidence', 0):.0%}")

                results.append({
                    "case": i,
                    "success": True,
                    "result": result
                })
            except Exception as e:
                print(f"❌ LLM 分析失败: {e}")
                results.append({
                    "case": i,
                    "success": False,
                    "error": str(e)
                })

        return results

    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor() as executor:
                future = executor.submit(asyncio.run, run_tests())
                results = future.result()
        else:
            results = loop.run_until_complete(run_tests())
    except RuntimeError:
        results = asyncio.run(run_tests())

    return results


def test_file_manager():
    """测试文件管理器"""
    print("\n" + "="*60)
    print("测试 3: ExperienceFileManager")
    print("="*60)

    logger = ExperienceLearningLogger(MEMORY_DATA_PATH)
    file_manager = ExperienceFileManager(MEMORY_DATA_PATH, logger)

    # 测试保存经验
    file_path = file_manager.save_experience_as_md(
        exp_id="exp_test1234",
        exp_type="correction",
        category="coding",
        user_message="你的代码有问题，变量名应该用 snake_case 而不是 camelCase",
        assistant_message="好的，我明白了。Python 变量命名应该使用 snake_case 格式。",
        summary="Python 变量命名规范：使用 snake_case 而非 camelCase",
        key_points=[
            "Python 变量名使用 snake_case 格式",
            "类名使用 PascalCase 格式",
            "常量使用全大写 SNAKE_CASE"
        ],
        tags=["python", "命名规范", "代码风格"],
        confidence=0.9,
        importance=0.8,
        session_id="test_session",
        date_str="2026-03-17",
        conversation_id="test_conv"
    )

    if file_path and file_path.exists():
        print(f"✅ MD 文件已创建: {file_path}")
        print(f"   文件大小: {file_path.stat().st_size} bytes")

        # 读取并显示部分内容
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()
            print(f"\n--- 文件内容预览 ---")
            print(content[:500])
            print("...")
    else:
        print(f"❌ MD 文件创建失败")

    # 检查目录结构
    exp_dir = file_manager.experiences_dir
    print(f"\n经验目录: {exp_dir}")
    print("子目录:")
    for subdir in exp_dir.iterdir():
        if subdir.is_dir():
            files = list(subdir.glob("*.md"))
            print(f"  {subdir.name}/: {len(files)} 个文件")

    return file_path


async def test_full_workflow():
    """测试完整工作流"""
    print("\n" + "="*60)
    print("测试 4: 完整经验学习工作流")
    print("="*60)

    storage_path = str(MEMORY_DATA_PATH)

    result = await run_experience_learning_with_llm(
        storage_path=storage_path,
        user_message="你之前的实现有个 bug，循环应该是 range(len(list)) 而不是 range(len(list)+1)，否则会越界",
        assistant_message="感谢指出！你说得对，range(len(list)) 才是正确的写法。我之前写错了，应该是 range(len(list)) 而不是 range(len(list)+1)，这样会导致索引越界错误。",
        session_id="test_session_001",
        date_str="2026-03-17",
        conversation_id="test_conv_001"
    )

    if result:
        print(f"✅ 完整工作流成功")
        print(f"   经验 ID: {result.get('id')}")
        print(f"   类型: {result.get('type')}")
        print(f"   文件: {result.get('file_path')}")
    else:
        print(f"⚠️ 未检测到经验或处理失败")

    return result


def main():
    """运行所有测试"""
    print("="*60)
    print("🧪 经验学习 Hook 测试套件")
    print("="*60)
    print(f"数据路径: {MEMORY_DATA_PATH}")
    print(f"时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

    results = {}

    # 测试 1: 日志记录器
    try:
        results["logger"] = test_logger()
        print("✅ 日志记录器测试通过")
    except Exception as e:
        print(f"❌ 日志记录器测试失败: {e}")
        import traceback
        traceback.print_exc()

    # 测试 2: LLM 分析器
    try:
        results["llm_analyzer"] = test_llm_analyzer()
        print("\n✅ LLM 分析器测试完成")
    except Exception as e:
        print(f"\n❌ LLM 分析器测试失败: {e}")
        import traceback
        traceback.print_exc()

    # 测试 3: 文件管理器
    try:
        results["file_manager"] = test_file_manager()
        print("\n✅ 文件管理器测试通过")
    except Exception as e:
        print(f"\n❌ 文件管理器测试失败: {e}")
        import traceback
        traceback.print_exc()

    # 测试 4: 完整工作流
    try:
        result = asyncio.run(test_full_workflow())
        results["full_workflow"] = result
        print("\n✅ 完整工作流测试完成")
    except Exception as e:
        print(f"\n❌ 完整工作流测试失败: {e}")
        import traceback
        traceback.print_exc()

    # 总结
    print("\n" + "="*60)
    print("📊 测试总结")
    print("="*60)

    passed = sum(1 for k, v in results.items() if v is not None)
    total = len(results)

    print(f"通过: {passed}/{total}")

    # 显示日志位置
    print(f"\n日志位置: {MEMORY_DATA_PATH}/logs/经验学习日志/")
    print(f"经验位置: {MEMORY_DATA_PATH}/experiences/")

    return results


if __name__ == "__main__":
    main()
