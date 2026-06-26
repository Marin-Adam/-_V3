"""Task planner — decomposes complex business questions into executable sub-tasks."""

import json
from dataclasses import dataclass, field

from openai import AsyncOpenAI

from app.core.config import get_settings

settings = get_settings()


@dataclass
class SubTask:
    id: str
    description: str
    tool_or_skill: str  # MCP tool name or Skill name
    params: dict = field(default_factory=dict)
    depends_on: list[str] = field(default_factory=list)  # IDs of prerequisite tasks


@dataclass
class Plan:
    original_query: str
    sub_tasks: list[SubTask]
    reasoning: str


class TaskPlanner:
    """LLM-driven task decomposition for complex analytics queries."""

    def __init__(self, llm_client: AsyncOpenAI = None):
        self.llm = llm_client or AsyncOpenAI(
            api_key=settings.QWEN_API_KEY or "sk-placeholder",
            base_url=settings.QWEN_BASE_URL or "https://api.openai.com/v1",
        )

    async def plan(self, query: str, available_tools: list[str], available_skills: list[str]) -> Plan:
        """Decompose a user query into a plan of sub-tasks."""
        prompt = f"""你是一个AI任务规划器。将用户的电商数据分析问题分解为可执行的子任务。

## 可用工具 (MCP)
{', '.join(available_tools)}

## 可用技能 (Skills)
{', '.join(available_skills)}

## 用户问题
{query}

## 输出格式
返回 JSON：
{{
  "reasoning": "规划思路",
  "sub_tasks": [
    {{"id": "1", "description": "...", "tool_or_skill": "query_sales_metrics", "params": {{...}}, "depends_on": []}},
    {{"id": "2", "description": "...", "tool_or_skill": "sales-anomaly-detection", "params": {{...}}, "depends_on": ["1"]}}
  ]
}}

注意：每个子任务必须使用可用的工具或技能。数据获取优先于分析。"""

        try:
            response = await self.llm.chat.completions.create(
                model="qwen-plus",
                messages=[{"role": "user", "content": prompt}],
                temperature=0.1,
                max_tokens=1024,
            )
            content = response.choices[0].message.content or "{}"
            # Extract JSON
            if "```json" in content:
                content = content.split("```json")[1].split("```")[0]
            elif "```" in content:
                content = content.split("```")[1].split("```")[0]

            data = json.loads(content)

            # Build the set of valid tool/skill names for validation
            valid_names = set(available_tools) | set(available_skills)

            sub_tasks = []
            for st in data.get("sub_tasks", []):
                tool_or_skill = st.get("tool_or_skill", "")
                # Validate and correct hallucinated tool/skill names
                if tool_or_skill not in valid_names:
                    if "sales" in tool_or_skill.lower() or "query" in tool_or_skill.lower():
                        tool_or_skill = "query_sales_metrics"
                    elif "traffic" in tool_or_skill.lower():
                        tool_or_skill = "query_traffic_data"
                    elif "inventory" in tool_or_skill.lower():
                        tool_or_skill = "query_inventory"
                    elif "competitor" in tool_or_skill.lower():
                        tool_or_skill = "query_competitor_prices"
                    elif "anomal" in tool_or_skill.lower():
                        tool_or_skill = "sales-anomaly-detection"
                    else:
                        tool_or_skill = "query_sales_metrics"  # Safe default
                    st["tool_or_skill"] = tool_or_skill
                sub_tasks.append(SubTask(**st))

            return Plan(
                original_query=query,
                sub_tasks=sub_tasks,
                reasoning=data.get("reasoning", ""),
            )
        except Exception:
            # Fallback: simple single-task plan
            return Plan(
                original_query=query,
                sub_tasks=[SubTask(id="1", description=query, tool_or_skill="query_sales_metrics", params={"time_range": "1h"})],
                reasoning="Using default single-task plan due to parsing error",
            )
