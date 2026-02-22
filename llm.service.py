# llm_service.py
import logging
import json
import os
from typing import Optional, Dict, Any, Tuple, List
from openai import AsyncOpenAI 
from error_handler import ErrorHandler


# --- MODIFIED: Model configurations for Perplexity Sonar models ---
MODEL_CONFIGS = {
    # Sonar Large - High quality, general purpose
    "sonar-large-online": {
        "max_tokens": 4096,
        "temperature": 0.1,
        "description": "Perplexity Sonar Large Online - High-quality reasoning with real-time web access"
    },
    # Sonar Small - Fast and efficient
    "sonar-small-online": {
        "max_tokens": 4096,
        "temperature": 0.1,
        "description": "Perplexity Sonar Small Online - Fast, efficient option with real-time web access"
    },
    # Sonar Large - Static, for reliability and cost control (no web search)
    "sonar-large-chat": {
        "max_tokens": 4096,
        "temperature": 0.1,
        "description": "Perplexity Sonar Large Chat - Strong reasoning without web search (static internal knowledge)"
    },
    # Llama 3 - A commonly available open model they host
    "llama-3.1-70b-versatile": {
        "max_tokens": 4096,
        "temperature": 0.1,
        "description": "Llama 3.1 70B - High-quality reasoning for complex log analysis (static internal knowledge)"
    }
}


# --- MODIFIED: Model fallback chain - ordered by preference (Sonar Priority) ---
MODEL_FALLBACK_CHAIN = [
    "sonar-large-chat",           # Primary - Strongest static reasoning model, perfect for analyzing internal logs/metadata.
    "sonar-large-online",         # Fallback 1 - Use Online model for external library/tool fixes if needed.
    "llama-3.1-70b-versatile",    # Fallback 2 - Highly capable Llama 3 for structured output.
    "sonar-small-online",         # Fallback 3 - Fastest online model for quick, simple analyses.
]


class LLMService:
    PERPLEXITY_BASE_URL = "https://api.perplexity.ai"

    def __init__(self, api_key: str, primary_model: str, error_handler: ErrorHandler):
        # ... (unchanged) ...
        self.api_key = api_key
        self.primary_model = primary_model
        self.error_handler = error_handler
        self.logger = logging.getLogger(__name__)
        
        if not self.api_key:
            raise ValueError("Perplexity API key is required")
        if not self.api_key.startswith("pplx-"):
             self.logger.warning("Perplexity API key format may be invalid (usually starts with pplx-)")
    
    # create_analysis_prompt (unchanged)
    def create_analysis_prompt(self, workflow_name: str, query_text: str, logs_text: str) -> str:
        """Create optimized prompt for workflow analysis"""
        return f"""Analyze the workflow logs and provide structured recommendations.

WORKFLOW: {workflow_name}
USER QUERY: {query_text}

RECENT LOGS:
{logs_text if logs_text else "No recent logs available."}

INSTRUCTIONS:
1. Analyze error patterns in the logs
2. Create practical transformation rules
3. Suggest actionable fixes with priorities
4. Keep analysis concise and practical

RESPONSE FORMAT - RAW JSON ONLY (no other text, no markdown):
{{
    "transformation_rules": ["clear rule 1", "specific rule 2", "actionable rule 3"],
    "error_analysis": "brief analysis of main issues",
    "suggested_fixes": [
        {{
            "fix": "specific action to take",
            "priority": "high",
            "impact": "what this will improve"
        }}
    ]
}}

IMPORTANT: Respond with valid JSON only, starting with {{ and ending with }}."""

    # _validate_json_response (unchanged)
    def _validate_json_response(self, response: str) -> bool:
        """Validate if the response is proper JSON"""
        try:
            parsed = json.loads(response)
            if isinstance(parsed, dict):
                return True
            return False
        except:
            return False
            
    # parse_ai_response (unchanged)
    def parse_ai_response(self, answer: str) -> Dict[str, Any]:
        """Parse and validate the AI response with proper error handling"""
        try:
            structured_response = json.loads(answer)
            
            transformation_rules = structured_response.get("transformation_rules")
            if isinstance(transformation_rules, str):
                transformation_rules = [transformation_rules]
            elif not transformation_rules or not isinstance(transformation_rules, list):
                transformation_rules = ["No transformation rules generated"]
            
            error_analysis = structured_response.get("error_analysis")
            if not error_analysis or not isinstance(error_analysis, str):
                error_analysis = "No error analysis provided"
            
            suggested_fixes = structured_response.get("suggested_fixes")
            if not suggested_fixes or not isinstance(suggested_fixes, list):
                suggested_fixes = [{"fix": "No specific fixes suggested", "priority": "medium", "impact": "Unknown"}]
            else:
                validated_fixes = []
                for fix in suggested_fixes:
                    if isinstance(fix, dict):
                        validated_fixes.append({
                            "fix": fix.get("fix", "Unknown fix"),
                            "priority": fix.get("priority", "medium"),
                            "impact": fix.get("impact", "Unknown impact")
                        })
                    elif isinstance(fix, str):
                        validated_fixes.append({
                            "fix": fix,
                            "priority": "medium",
                            "impact": "General improvement"
                        })
                suggested_fixes = validated_fixes
            
            return {
                "transformation_rules": transformation_rules,
                "error_analysis": error_analysis,
                "suggested_fixes": suggested_fixes
            }
            
        except json.JSONDecodeError as e:
            self.logger.error(f"JSON parsing failed: {str(e)}")
            return {
                "transformation_rules": ["JSON parsing error in AI response"],
                "error_analysis": f"Failed to parse AI response as JSON: {str(e)}",
                "suggested_fixes": [{
                    "fix": "Check AI response format and prompt engineering",
                    "priority": "high",
                    "impact": "Ensure consistent JSON output from AI model"
                }]
            }

    # query_perplexity_model (unchanged logic, only model list changed)
    async def query_perplexity_model(
        self,
        prompt: str, 
        model_name: str, 
        workflow_id: Optional[int] = None
    ) -> Tuple[Optional[str], Optional[str], str]:
        """Query a specific Perplexity model (via OpenAI-compatible client)"""
        try:
            client = AsyncOpenAI(
                api_key=self.api_key,
                base_url=self.PERPLEXITY_BASE_URL
            )
            
            model_config = MODEL_CONFIGS.get(model_name, {
                "max_tokens": 2048,
                "temperature": 0.1
            })
            
            system_prompt = """You are a technical analyst specializing in workflow optimization and error resolution. 
You provide clear, actionable recommendations in structured JSON format.
You always respond with valid JSON only - no additional text, no explanations, no markdown formatting."""

            self.logger.info(f"Attempting to query Perplexity model: {model_name}")
            
            chat_completion = await client.chat.completions.create(
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": prompt}
                ],
                model=model_name,
                temperature=model_config["temperature"],
                max_tokens=model_config["max_tokens"],
                top_p=0.9,
                stream=False,
                timeout=30.0
            )
            
            response_content = chat_completion.choices[0].message.content
            
            # Enhanced cleaning for responses
            response_content = response_content.strip()
            if response_content.startswith("```json"):
                response_content = response_content[7:].strip()
            if response_content.endswith("```"):
                response_content = response_content[:-3].strip()
            if response_content.startswith("```"):
                response_content = response_content[3:].strip()
                
            self.logger.info(f"Successfully got response from Perplexity model: {model_name}")
            return response_content, None, model_name
            
        except Exception as e:
            error_message = f"Perplexity API error with model {model_name}: {str(e)}"
            if workflow_id:
                await self.error_handler.log_error(workflow_id, "API_Error", error_message)
            self.logger.error(error_message)
            return None, error_message, model_name

    # query_with_fallback (unchanged logic, only model list changed)
    async def query_with_fallback(
        self,
        prompt: str,
        workflow_id: Optional[int] = None
    ) -> Tuple[Optional[str], Optional[str], Optional[str], List[Dict]]:
        """Query Perplexity with automatic model fallback"""
        
        model_chain = [self.primary_model] + [model for model in MODEL_FALLBACK_CHAIN if model != self.primary_model]
        
        attempts = []
        last_error = None
        
        for model_name in model_chain:
            try:
                answer, error, used_model = await self.query_perplexity_model( 
                    prompt, model_name, workflow_id
                )
                
                attempts.append({
                    "model": used_model,
                    "success": answer is not None,
                    "error": error
                })
                
                if answer and self._validate_json_response(answer):
                    self.logger.info(f"Successfully used model: {used_model} after {len(attempts)} attempts")
                    return answer, None, used_model, attempts
                elif answer:
                    last_error = f"Model {used_model} returned invalid JSON format"
                    self.logger.warning(f"Model {used_model} returned invalid JSON, trying next model...")
                    continue
                    
            except Exception as e:
                attempts.append({
                    "model": model_name,
                    "success": False,
                    "error": str(e)
                })
                last_error = str(e)
                self.logger.warning(f"Model {model_name} failed, trying next model...")
                continue
        
        error_msg = f"All models failed. Attempts: {attempts}. Last error: {last_error}"
        self.logger.error(error_msg)
        return None, error_msg, None, attempts

    # health_check (unchanged logic, only model list changed)
    async def health_check(self) -> Dict[str, Any]:
        """Check if Perplexity API is accessible with model testing"""
        results = {}
        
        for model_name in MODEL_FALLBACK_CHAIN[:2]: 
            try:
                client = AsyncOpenAI(
                    api_key=self.api_key,
                    base_url=self.PERPLEXITY_BASE_URL
                )
                test_completion = await client.chat.completions.create(
                    messages=[{"role": "user", "content": "Say 'OK'"}],
                    model=model_name,
                    max_tokens=10,
                    timeout=10.0
                )
                results[model_name] = {
                    "status": "healthy",
                    "response": test_completion.choices[0].message.content
                }
            except Exception as e:
                results[model_name] = {
                    "status": "unhealthy",
                    "error": str(e)
                }
        
        healthy_models = [model for model, result in results.items() if result["status"] == "healthy"]
        
        return {
            "overall_status": "healthy" if healthy_models else "unhealthy",
            "available_models": healthy_models,
            "model_details": results
        }
        
    # get_model_info (unchanged logic, only model list changed)
    def get_model_info(self) -> Dict[str, Any]:
        """Get information about available Perplexity models"""
        available_models = {}
        
        for model_name in MODEL_FALLBACK_CHAIN:
            if model_name in MODEL_CONFIGS:
                available_models[model_name] = MODEL_CONFIGS[model_name]
        
        return {
            "primary_model": self.primary_model,
            "fallback_chain": MODEL_FALLBACK_CHAIN,
            "available_models": available_models
        }


# Utility function to create LLM service instance
def create_llm_service(error_handler: ErrorHandler) -> LLMService:
    """Factory function to create LLMService instance"""
    api_key = os.getenv("PERPLEXITY_API_KEY") 
    # Changed default to a strong, static Sonar model
    primary_model = os.getenv("PERPLEXITY_MODEL", "sonar-large-chat") 
    
    if not api_key:
        raise ValueError("PERPLEXITY_API_KEY environment variable is required")
    
    return LLMService(api_key, primary_model, error_handler)