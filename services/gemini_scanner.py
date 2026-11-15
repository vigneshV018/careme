import os
import json
import logging
from typing import List, Dict, Any

from config import GEMINI_API_KEY, GEMINI_MODEL, DEMO_MODE

logger = logging.getLogger("careme.gemini")

# Standard schedule time mapping required by specification
TIME_MAPPING = {
    "morning": "08:00",
    "afternoon": "14:00",
    "evening": "18:00",
    "night": "21:00"
}

def clean_json_text(text: str) -> str:
    """Strip any markdown fences or preamble before JSON parsing."""
    cleaned = text.strip()
    if cleaned.startswith("```json"):
        cleaned = cleaned[7:]
    elif cleaned.startswith("```"):
        cleaned = cleaned[3:]
    if cleaned.endswith("```"):
        cleaned = cleaned[:-3]
    return cleaned.strip()

def sanitize_medicine_item(item: Dict[str, Any]) -> Dict[str, Any]:
    """Ensures extracted prescription item adheres to strict format rules."""
    name = str(item.get("name", "unclear")).strip()
    dosage = str(item.get("dosage", "unclear")).strip()
    instructions = str(item.get("instructions", "Take as prescribed by doctor")).strip()

    # Times validation: must be subset of morning/afternoon/evening/night
    valid_time_keys = {"morning", "afternoon", "evening", "night"}
    raw_times = item.get("times", [])
    if isinstance(raw_times, str):
        raw_times = [t.strip().lower() for t in raw_times.replace(",", " ").split() if t.strip()]

    times = []
    for t in raw_times:
        clean_t = str(t).strip().lower()
        if clean_t in valid_time_keys and clean_t not in times:
            times.append(clean_t)

    if not times:
        times = ["morning"]  # Safe default if not specified

    # Duration
    raw_duration = item.get("duration_days", 30)
    try:
        duration_days = int(raw_duration)
    except (ValueError, TypeError):
        duration_days = 30

    return {
        "name": name if name else "unclear",
        "dosage": dosage if dosage else "unclear",
        "times": times,
        "duration_days": duration_days,
        "instructions": instructions if instructions else "Take as directed"
    }

def get_demo_fallback_items() -> List[Dict[str, Any]]:
    """Sample prescription extraction for hackathon demo fallback."""
    return [
        {
            "name": "Telmisartan",
            "dosage": "40mg",
            "times": ["morning"],
            "duration_days": 30,
            "instructions": "Take once daily in the morning after breakfast"
        },
        {
            "name": "Pantoprazole",
            "dosage": "40mg",
            "times": ["morning"],
            "duration_days": 15,
            "instructions": "Take 30 minutes before morning breakfast"
        },
        {
            "name": "Calcium & Vitamin D3",
            "dosage": "500mg",
            "times": ["afternoon"],
            "duration_days": 60,
            "instructions": "Take with lunch or a glass of warm milk"
        }
    ]

def scan_prescription_with_gemini(image_bytes: bytes, mime_type: str = "image/jpeg") -> Dict[str, Any]:
    """
    Sends prescription image to Google Gemini (gemini-2.5-flash) and extracts
    structured medication list as strict JSON:
    [{name, dosage, times (morning/afternoon/evening/night), duration_days, instructions}]
    """
    if not image_bytes or len(image_bytes) == 0:
        return {
            "success": False,
            "error": "No image file provided. Please upload or capture a photo of the prescription.",
            "items": []
        }

    api_key = os.getenv("GEMINI_API_KEY", GEMINI_API_KEY).strip()

    if not api_key or "your-gemini" in api_key.lower():
        if DEMO_MODE:
            logger.warning("GEMINI_API_KEY not configured. DEMO_MODE is true: returning demonstration prescription extraction.")
            return {
                "success": True,
                "is_demo_fallback": True,
                "message": "Demo Mode: GEMINI_API_KEY not configured in .env. Showing sample extracted prescription. Configure your API key for live vision analysis.",
                "items": get_demo_fallback_items()
            }
        else:
            return {
                "success": False,
                "error": "Gemini API key is not configured. Please add GEMINI_API_KEY to your .env file to enable live prescription scanning.",
                "items": []
            }

    try:
        from google import genai
        from google.genai import types

        client = genai.Client(api_key=api_key)

        prompt = (
            "You are an expert clinical medical transcription AI for an elderly healthcare assistant platform. "
            "Examine this doctor's prescription image with extreme medical precision and extract all prescribed medicines.\n\n"
            "Respond ONLY with a valid JSON array of objects conforming exactly to this structure:\n"
            "[\n"
            "  {\n"
            "    \"name\": \"Medicine name\",\n"
            "    \"dosage\": \"Dosage (e.g. 500mg, 10mg)\",\n"
            "    \"times\": [\"morning\", \"night\"],\n"
            "    \"duration_days\": 30,\n"
            "    \"instructions\": \"Administration instructions (e.g. Take after meals with warm water)\"\n"
            "  }\n"
            "]\n\n"
            "MANDATORY TRANSCRIPTION RULES:\n"
            "1. STRICT JSON ONLY. Never output markdown code block fences (do NOT include ```json or ```).\n"
            "2. DO NOT GUESS unreadable or ambiguous text. If any drug name, dosage, or frequency is smudged, unclear, or illegible, mark that field as \"unclear\".\n"
            "3. 'times' MUST be an array containing ONLY one or more of these exact lowercase tokens: [\"morning\", \"afternoon\", \"evening\", \"night\"]. "
            "If once a day morning, use [\"morning\"]. If twice a day, use [\"morning\", \"night\"]. If 3 times a day, use [\"morning\", \"afternoon\", \"night\"]. If bedtime/night, use [\"night\"].\n"
            "4. If duration in days is not specified, default to 30.\n"
            "5. If administration instructions are not explicitly noted, write 'As directed by doctor'."
        )

        model_name = os.getenv("GEMINI_MODEL", GEMINI_MODEL).strip() or "gemini-2.5-flash"
        logger.info(f"Sending prescription image ({len(image_bytes)} bytes, {mime_type}) to Gemini model '{model_name}'...")

        part_image = types.Part.from_bytes(data=image_bytes, mime_type=mime_type)

        response = client.models.generate_content(
            model=model_name,
            contents=[part_image, prompt],
            config=types.GenerateContentConfig(
                temperature=0.1,
                response_mime_type="application/json"
            )
        )

        raw_output = response.text or ""
        clean_json = clean_json_text(raw_output)

        if not clean_json:
            return {
                "success": False,
                "error": "Gemini returned an empty response. Please verify the prescription image is clear and well-lit.",
                "items": []
            }

        parsed = json.loads(clean_json)

        # Handle object wrapping array like {"medicines": [...]} or {"prescriptions": [...]}
        if isinstance(parsed, dict):
            for key in ["medicines", "prescriptions", "items", "drugs", "data"]:
                if key in parsed and isinstance(parsed[key], list):
                    parsed = parsed[key]
                    break

        if not isinstance(parsed, list):
            parsed = [parsed]

        sanitized_items = [sanitize_medicine_item(item) for item in parsed if isinstance(item, dict)]

        if not sanitized_items:
            return {
                "success": False,
                "error": "No medications could be deciphered from this image. Please re-take a clearer photo or enter details manually below.",
                "items": []
            }

        return {
            "success": True,
            "items": sanitized_items,
            "raw": clean_json,
            "model_used": model_name
        }

    except json.JSONDecodeError as jde:
        logger.error(f"Failed to parse Gemini response as JSON: {jde}. Raw response: {raw_output if 'raw_output' in locals() else 'None'}")
        return {
            "success": False,
            "error": "Could not format prescription into structured data. Please verify image clarity or enter manually below.",
            "items": []
        }
    except Exception as e:
        logger.error(f"Error in scan_prescription_with_gemini: {e}", exc_info=True)
        return {
            "success": False,
            "error": f"Gemini scanner error: {str(e)}. You can still enter your prescription details manually below.",
            "items": []
        }

