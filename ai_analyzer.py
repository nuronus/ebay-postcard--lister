"""AI-powered image analysis using OpenAI GPT-4 Vision."""

import json
from dataclasses import dataclass
from openai import OpenAI

from config import config
from image_processor import image_to_base64


@dataclass
class ListingContent:
    """Generated content for an eBay listing."""
    title: str
    description: str


ANALYSIS_PROMPT = """Analyze this postcard image and generate an eBay listing optimized for search and sales.

IMPORTANT: These are NEW postcards, NOT vintage. Do NOT use words like "vintage", "antique", "real photo", "RPPC", or era terms like "1920s".

Generate a JSON response with these fields:

1. "title": An SEO-optimized title (MAXIMUM 80 characters)
   - MUST include "Art Postcard" in the title
   - Include: location, subject, key features
   - Use descriptive keywords buyers search for
   - Example: "Atlantic City NJ Boardwalk Beach Art Postcard New Jersey Shore Souvenir"

2. "description": A detailed HTML description including:
   - What the postcard depicts (scene, landmarks, views, etc.)
   - Location details (city, state, region)
   - Card features (glossy, matte, photo quality)
   - Condition: Brand new
   - Standard postcard size (approximately 4" x 6")
   - Great for: mailing, collecting, scrapbooking, framing

   Use <p>, <br>, and <b> tags for formatting.

Focus on location-based keywords and appealing to tourists, travelers, and collectors of modern postcards.

Respond ONLY with valid JSON, no other text:
{"title": "...", "description": "..."}"""


def analyze_image(image_bytes: bytes) -> ListingContent:
    """
    Analyze a postcard image using GPT-4 Vision.

    Args:
        image_bytes: JPEG image data

    Returns:
        ListingContent with generated title and description
    """
    client = OpenAI(api_key=config.OPENAI_API_KEY)

    base64_image = image_to_base64(image_bytes)

    response = client.chat.completions.create(
        model="gpt-4o",
        messages=[
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": ANALYSIS_PROMPT},
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:image/jpeg;base64,{base64_image}",
                            "detail": "high"
                        }
                    }
                ]
            }
        ],
        max_tokens=1000
    )

    content = response.choices[0].message.content.strip()

    if content.startswith("```"):
        content = content.split("\n", 1)[1]
        content = content.rsplit("```", 1)[0]

    data = json.loads(content)

    title = data["title"]

    # Ensure "Art Postcard" is in the title
    if "art postcard" not in title.lower():
        if "postcard" in title.lower():
            title = title.replace("Postcard", "Art Postcard").replace("postcard", "Art Postcard")
        else:
            title = title + " Art Postcard"

    # Truncate to 80 characters
    title = title[:80]

    return ListingContent(
        title=title,
        description=data["description"]
    )
