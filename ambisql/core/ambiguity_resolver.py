import json
import re
from typing import List

from ambisql.core.cq_generator import CQGenerator
from ambisql.prompts.ambiguity_detection_prompt import (
    QuestionRefine_prompt,
    AmbiguityDetection_prompt,
    AmbiguityDetection_examples,
)
from ambisql.core.schema_generator import SchemaGenerator
from ambisql.core.preference_index import PreferenceTree
from ambisql.utils import LLMCaller
from ambisql.utils.parse import (
    format_response, 
    parse_json_response
)

class AmbiguityResolver:
    """
    Resolves ambiguities in natural language questions for SQL query generation.
    
    This class detects ambiguities in user questions, generates clarification questions,
    and refines questions based on user responses to produce unambiguous SQL queries.
    """
    def __init__(self, db_name, path, question, model):
        """
        Initialize the ambiguity resolver.
        
        Args:
            db_name: Name of the database to query
            path: Path to the database directory
            question: The user's natural language question
            model: The LLM model to use for ambiguity detection and resolution
        """
        self.db_name = db_name
        self.path = path
        self.question = question
        self.llm_caller = LLMCaller(model)
        self.schema_generator = SchemaGenerator(db_name, path, question)
        self.intention_model = PreferenceTree(self.llm_caller)
        self.cq_generator = CQGenerator()
        
    def ambi_detection(self):
        """
        Detect ambiguities in the initial question.
        
        Returns:
            JSON string containing either:
            - Clarification questions if ambiguities are found (is_clarified=False)
            - Refined question and evidence if no ambiguities (is_clarified=True)
        """
        flag, question_set = self.check_ambiguity()
        if flag:          
            question_set = self.rewrite_clarification_question(question_set)
            return format_response(is_clarified=False, q_set=question_set)
        else:
            return self.format_response(self.question, self.intention_model)
        

    def ambi_correction(self, message):
        """
        Process user clarifications and check for remaining ambiguities.
        
        Args:
            message: JSON string containing clarification answers and additional info
            
        Returns:
            JSON string containing either:
            - Remaining clarification questions if ambiguities persist (is_clarified=False)
            - Refined question and evidence if all ambiguities resolved (is_clarified=True)
        """
        flag = None
        message_parsed = json.loads(message)
        self.intention_model.update_tree(message_parsed["qa_set"])
        if not message_parsed["qa_set"] and message_parsed["additional_info"].strip() == "":
            flag = False
        else:
            flag, question_set = self.check_ambiguity(
                initial_detection=False, message=message
            )
        
        if flag:
            question_set = self.rewrite_clarification_question(question_set)
            return format_response(is_clarified=False, q_set=question_set)
        else:
            return self.format_response(self.question, self.intention_model)
        
    def check_ambiguity(self, initial_detection: bool = True, message: str = ''):
        """
        Check if the question contains ambiguities using LLM-based detection.
        
        Args:
            message: JSON string containing additional info and clarification answers.
                    Empty string for initial detection.
        
        Returns:
            Tuple of (has_ambiguity: bool, question_set: list or None):
            - If ambiguities found: (True, list of ambiguity questions)
            - If no ambiguities: (False, None)
        """
        ambiguity_detection_prompt = ""

        if initial_detection:
            
            # print(f"Formatted full schema JSON: {self.schema_generator.formatted_full_schema_json}")
            ambiguity_detection_prompt = AmbiguityDetection_prompt.format(
                question=self.question,
                schema=self.schema_generator.formatted_full_schema_json,
                evidence=None,
                examples=AmbiguityDetection_examples, #note:we can provide our examples here to help the model better understand the task
            )
        else:
            message_dict = json.loads(message)
            additional_info = message_dict["additional_info"].strip()
            if additional_info:
                self.question = self.question_refine(additional_info)
            print(f"Evidence: {self.intention_model.traverse()}")

            ambiguity_detection_prompt = AmbiguityDetection_prompt.format(
                question=self.question,
                schema=self.schema_generator.formatted_full_schema_json,
                evidence=self.intention_model.traverse(),
                examples=AmbiguityDetection_examples,
            )

            
        query = [
            {"role": "system", "content": "You are a helpful assistant to find out inherent ambiguity in a natural language statement. Return only the result with no explanation."},
            {"role": "user", "content": ambiguity_detection_prompt},
        ]
        response = self.llm_caller.call(query)
        res = parse_json_response(response)

        if res["has_ambiguity"]:
            filtered_question_set = self.filter_false_positive_ambiguities(
                res["question_set"], self.question
            )
            if filtered_question_set:
                return True, filtered_question_set
            return False, None
        else:
            return res["has_ambiguity"], None

    def find_exact_unique_column_matches(self, question_text):
        question_lower = question_text.lower()
        matches = []
        seen_columns = set()

        for table_name, columns in self.schema_generator.formatted_full_schema_json.items():
            for column_name in columns.keys():
                normalized_column = column_name.lower()
                pattern = rf"(?<![a-z0-9_]){re.escape(normalized_column)}(?![a-z0-9_])"
                if re.search(pattern, question_lower):
                    seen_columns.add((table_name, column_name))

        unique_by_column = {}
        for table_name, column_name in seen_columns:
            unique_by_column.setdefault(column_name.lower(), []).append((table_name, column_name))

        for column_matches in unique_by_column.values():
            if len(column_matches) == 1:
                matches.extend(column_matches)

        return matches

    def tokenize_text(self, text):
        text = text.lower().replace("_", " ")
        return {
            token
            for token in re.findall(r"[a-z0-9]+", text)
            if token and token not in {"the", "a", "an", "all", "show", "list"}
        }

    def find_strong_natural_language_matches(self, question_text):
        question_tokens = self.tokenize_text(question_text)
        if not question_tokens:
            return []

        scored_matches = []
        for table_name, columns in self.schema_generator.formatted_full_schema_json.items():
            for column_name, metadata in columns.items():
                column_text_parts = [
                    column_name,
                    metadata.get("column_description", ""),
                    metadata.get("value_description", ""),
                ]
                column_tokens = self.tokenize_text(" ".join(column_text_parts))
                overlap = question_tokens & column_tokens
                score = len(overlap)

                # Favor especially strong lexical signals for business metrics.
                if "percent" in column_tokens and "percentage" in question_tokens:
                    score += 1
                if "occupancy" in column_tokens and "occupancy" in question_tokens:
                    score += 2
                if "physical" in column_tokens and "physical" in question_tokens:
                    score += 2
                if "property" in column_tokens and "properties" in question_tokens:
                    score += 1

                if score > 0:
                    scored_matches.append(
                        {
                            "table_name": table_name,
                            "column_name": column_name,
                            "score": score,
                            "overlap": overlap,
                        }
                    )

        if not scored_matches:
            return []

        scored_matches.sort(key=lambda item: item["score"], reverse=True)
        best_score = scored_matches[0]["score"]
        best_matches = [
            item for item in scored_matches if item["score"] == best_score
        ]

        # Only accept a natural-language grounding when it is clearly stronger
        # than the next candidate, or when it is the only strong candidate.
        second_score = scored_matches[1]["score"] if len(scored_matches) > 1 else -1
        if best_score >= 3 and (len(best_matches) == 1 or best_score >= second_score + 2):
            return best_matches

        return []

    def has_explicit_literal_condition(self, question_text):
        return bool(
            re.search(r"(<=|>=|=|<|>)\s*[-+]?\d+(\.\d+)?", question_text)
            or re.search(r"(<=|>=|=|<|>)\s*['\"][^'\"]+['\"]", question_text)
        )

    def filter_false_positive_ambiguities(self, question_set, question_text):
        if not question_set:
            return []

        exact_matches = self.find_exact_unique_column_matches(question_text)
        natural_language_matches = self.find_strong_natural_language_matches(question_text)
        exact_column_names = {column_name.lower() for _, column_name in exact_matches}
        natural_language_column_names = {
            match["column_name"].lower() for match in natural_language_matches
        }
        explicit_condition = self.has_explicit_literal_condition(question_text)

        filtered_question_set = []
        for item in question_set:
            level_2_label = item.get("level_2_label", "")
            item_text = " ".join(
                [
                    item.get("question", ""),
                    json.dumps(item.get("description", ""), ensure_ascii=False),
                ]
            ).lower()

            grounded_column_names = exact_column_names | natural_language_column_names

            if level_2_label == "AmbiSchema" and grounded_column_names:
                if any(column_name in item_text for column_name in grounded_column_names):
                    continue

            if level_2_label == "AmbiValue" and explicit_condition and grounded_column_names:
                if any(
                    column_name in item_text or column_name in question_text.lower()
                    for column_name in grounded_column_names
                ):
                    continue

            filtered_question_set.append(item)

        return filtered_question_set

    def question_refine(self, additional_info):
        """
        Refine the original question by incorporating additional information.
        
        Args:
            additional_info: Additional context or clarification provided by the user
            
        Returns:
            Refined question string that merges the original question with new information
        """
        question_refine_prompt = QuestionRefine_prompt.format(
            question=self.question, additional_info=additional_info
        )
        query = [
            {"role": "system", "content": "You are an expert specializing in query refinement. Your purpose is to merge and consolidate user questions with new information. Respond ONLY with the refined question. Do not add any explanation, formatting, or extra text."},
            {"role": "user", "content": question_refine_prompt},
        ]
        response = self.llm_caller.call(query)
        return response

    def rewrite_clarification_question(self, question_set: List[dict]):
        """
        Rewrite clarification questions and generate choice options for each ambiguity.
        
        For each ambiguity question, this method generates multiple choice options
        to help users clarify their intent.
        
        Args:
            question_set: List of ambiguity question dictionaries
            
        Returns:
            Modified question_set with 'choices' field added to each question
        """
        return self.cq_generator.generate_clarification_question(question_set, self.llm_caller)
    
    def format_response(self, question, intention_model):
        """
        Format the final response when all ambiguities are resolved.
        
        Args:
            question: The refined question after ambiguity resolution
            intention_model: PreferenceTree instance containing user preferences/evidence
            
        Returns:
            JSON string containing the clarified question and evidence for SQL generation
        """
        response = {
            "is_clarified" : True,
            "question": question,
            "question_set" : None,
            "evidence": intention_model.traverse()
        }
        return json.dumps(response, ensure_ascii=False) 
