import json
from typing import List

from ambisql.prompts.cq_generation_prompt import CQ_Generation_prompt, CQ_Template_prompt
from ambisql.utils.llm_caller import LLMCaller
from ambisql.utils.parse import parse_json_response

class CQGenerator:
    def __init__(self):
        self.templates = CQ_Template_prompt  

    def generate_clarification_question(
        self, 
        question_set: List[dict], 
        llm_caller:LLMCaller
    ) -> List[dict]:
        for item in question_set:
            description_str = ""
            if isinstance(item.get('description'), dict):
                description_str = json.dumps(item['description'], indent=2)
            elif isinstance(item.get('description'), str):
                description_str = item['description']
            else:
                description_str = str(item['description'])

            
            # print(f"Description string: {description_str}")
            rewrite_clarification_question_prompt = CQ_Generation_prompt.format(
                question=item['question'], description=description_str, templates=self.templates
            )

            query = [
                {"role": "system", "content": "You are an expert that excels at simplifying complex technical information into clear, user-friendly, multiple-choice options."},
                {"role": "user", "content": rewrite_clarification_question_prompt},
            ]

            try:
                raw_response = llm_caller.call(query)
                parsed_response = parse_json_response(raw_response)
                
                choices_list = parsed_response.get('choices', [])
                
                if isinstance(choices_list, list) and all(isinstance(c, str) for c in choices_list):
                    item['choices'] = choices_list
                else:
                    print(f"Warning: LLM response for 'choices' was not a list of strings. Got: {choices_list}")
                    item['choices'] = [] 
                

            except json.JSONDecodeError as e:
                print(f"Error: Failed to decode JSON from LLM response. Error: {e}")
                print(f"Raw response was: {raw_response}")
                item['choices'] = []
            except Exception as e:
                print(f"An unexpected error occurred: {e}")
                item['choices'] = []

        return question_set
