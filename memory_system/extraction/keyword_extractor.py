"""关键词提取器 - 从对话中提取关键词"""
from dataclasses import dataclass
from typing import List, Dict, Any, Optional
import re
from collections import Counter


@dataclass
class ExtractedKeyword:
    """提取的关键词"""
    word: str
    type: str  # topic, technology, action, entity
    weight: float
    source: str  # 来源句子或上下文


class KeywordExtractor:
    """
    关键词提取器

    策略：
    1. 技术词汇识别（编程语言、框架、工具等）
    2. 话题词汇识别（项目名、功能名等）
    3. 动作词汇识别（讨论、实现、解决等）
    4. 实体识别（人名、地名、组织等）
    """

    # 技术词汇列表（常见）
    TECH_KEYWORDS = {
        # 编程语言
        "python", "java", "javascript", "typescript", "go", "rust", "cpp", "c++",
        "ruby", "php", "swift", "kotlin", "scala", "r", "matlab",
        # 框架和库
        "django", "flask", "fastapi", "react", "vue", "angular", "spring",
        "express", "nestjs", "nextjs", "pytorch", "tensorflow", "keras",
        "langchain", "transformers", "pandas", "numpy", "scipy",
        # 数据库
        "mysql", "postgresql", "mongodb", "redis", "elasticsearch",
        "sqlite", "oracle", "sqlserver",
        # 工具和平台
        "docker", "kubernetes", "aws", "azure", "gcp", "git", "linux",
        "nginx", "apache", "kafka", "rabbitmq",
        # AI相关
        "llm", "gpt", "claude", "ai", "ml", "nlp", "cv", "dl", "机器学习",
        "深度学习", "自然语言处理", "人工智能", "大模型", "agent", "rag",
    }

    # 动作词汇
    ACTION_KEYWORDS = {
        "讨论", "实现", "解决", "优化", "设计", "开发", "部署", "测试",
        "调试", "重构", "分析", "实现", "创建", "配置", "集成", "部署",
        "implement", "develop", "design", "optimize", "solve", "fix",
        "test", "deploy", "configure", "integrate", "debug", "refactor",
    }

    # 中英文停用词
    STOPWORDS = {
        "的", "了", "是", "在", "我", "有", "和", "就", "不", "人", "都",
        "一", "一个", "上", "也", "很", "到", "说", "要", "去", "你",
        "会", "着", "没有", "看", "好", "自己", "这", "the", "a", "an",
        "is", "are", "was", "were", "be", "been", "being", "have", "has",
        "had", "do", "does", "did", "will", "would", "could", "should",
        "may", "might", "must", "shall", "can", "need", "dare", "ought",
        "used", "to", "of", "in", "for", "on", "with", "at", "by", "from",
        "as", "into", "through", "during", "before", "after", "above",
        "below", "between", "under", "again", "further", "then", "once",
        "here", "there", "when", "where", "why", "how", "all", "each",
        "few", "more", "most", "other", "some", "such", "no", "nor", "not",
        "only", "own", "same", "so", "than", "too", "very", "just", "and",
        "but", "if", "or", "because", "until", "while", "what", "which",
        "who", "whom", "this", "that", "these", "those", "am", "it", "its",
    }

    def __init__(self):
        # 编译正则表达式
        self.chinese_pattern = re.compile(r'[\u4e00-\u9fff]+')
        self.english_pattern = re.compile(r'[a-zA-Z]+')
        self.number_pattern = re.compile(r'\d+')

    async def extract(
        self,
        content: str,
        max_keywords: int = 10,
        existing_keywords: Optional[List[str]] = None
    ) -> List[Dict[str, Any]]:
        """
        从内容中提取关键词

        Args:
            content: 要提取的文本内容
            max_keywords: 最大关键词数量
            existing_keywords: 已有关键词（用于优先匹配）

        Returns:
            关键词列表，包含 word, type, weight
        """
        keywords = []
        existing_keywords = existing_keywords or []

        # 1. 优先匹配已有关键词
        for kw in existing_keywords:
            if kw.lower() in content.lower():
                keywords.append({
                    "word": kw,
                    "type": "topic",
                    "weight": 0.9
                })

        # 2. 提取技术词汇
        content_lower = content.lower()
        for tech in self.TECH_KEYWORDS:
            if tech in content_lower:
                # 检查是否已经添加
                if not any(k["word"] == tech for k in keywords):
                    keywords.append({
                        "word": tech,
                        "type": "technology",
                        "weight": 0.8
                    })

        # 3. 提取动作词汇
        for action in self.ACTION_KEYWORDS:
            if action in content_lower:
                if not any(k["word"] == action for k in keywords):
                    keywords.append({
                        "word": action,
                        "type": "action",
                        "weight": 0.6
                    })

        # 4. 提取项目/功能名称模式
        project_patterns = [
            r'(\w+)项目',
            r'(\w+)系统',
            r'(\w+)功能',
            r'(\w+)模块',
            r'(\w+)服务',
            r'(\w+)接口',
            r'(\w+)\s*project',
            r'(\w+)\s*system',
        ]

        for pattern in project_patterns:
            matches = re.finditer(pattern, content, re.IGNORECASE)
            for match in matches:
                word = match.group(0)
                if not any(k["word"] == word for k in keywords):
                    keywords.append({
                        "word": word,
                        "type": "topic",
                        "weight": 0.85
                    })

        # 5. 提取引号中的内容（通常是重要概念）
        quoted_pattern = r'[""「」『』]([^""「」『』]+)[""「」『』]'
        for match in re.finditer(quoted_pattern, content):
            word = match.group(1)
            if len(word) >= 2 and len(word) <= 20:
                if word.lower() not in self.STOPWORDS:
                    if not any(k["word"] == word for k in keywords):
                        keywords.append({
                            "word": word,
                            "type": "entity",
                            "weight": 0.7
                        })

        # 6. 词频分析补充
        freq_keywords = self._frequency_analysis(content, existing_keywords)
        for kw in freq_keywords:
            if not any(k["word"] == kw["word"] for k in keywords):
                keywords.append(kw)

        # 按权重排序并限制数量
        keywords.sort(key=lambda x: x["weight"], reverse=True)
        return keywords[:max_keywords]

    def _frequency_analysis(
        self,
        content: str,
        exclude_words: List[str]
    ) -> List[Dict[str, Any]]:
        """词频分析"""
        # 简单分词（中文按字符，英文按空格）
        words = []

        # 提取中文词组（简单实现：2-4字的组合）
        chinese_matches = self.chinese_pattern.findall(content)
        for text in chinese_matches:
            for i in range(len(text) - 1):
                for length in [4, 3, 2]:
                    if i + length <= len(text):
                        word = text[i:i + length]
                        if word not in self.STOPWORDS:
                            words.append(word)

        # 提取英文单词
        english_matches = self.english_pattern.findall(content)
        words.extend([w.lower() for w in english_matches if len(w) >= 3])

        # 统计频率
        counter = Counter(words)

        # 过滤并返回
        result = []
        for word, count in counter.most_common(10):
            if word not in self.STOPWORDS and word not in exclude_words:
                if count >= 2:  # 至少出现2次
                    result.append({
                        "word": word,
                        "type": "topic",
                        "weight": min(0.5 + count * 0.1, 0.8)
                    })

        return result[:5]

    def extract_from_conversation(
        self,
        user_message: str,
        assistant_message: str
    ) -> List[Dict[str, Any]]:
        """从对话中提取关键词"""
        combined = f"{user_message} {assistant_message}"
        return self.extract(combined)
