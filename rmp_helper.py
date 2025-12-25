import requests
import json
import base64
import logging
from datetime import datetime

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

HEADERS = {
    "Authorization": "Basic dGVzdDp0ZXN0",
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/87.0.4280.88 Safari/537.36",
    "Content-Type": "application/json"
}

GRAPHQL_URL = "https://www.ratemyprofessors.com/graphql"

PROFESSOR_QUERY = """
query RatingsListQuery($id: ID!) {
  node(id: $id) {
    ... on Teacher {
      firstName
      lastName
      department
      avgRating
      avgDifficulty
      numRatings
      wouldTakeAgainPercent
      school {
        name
        id
      }
    }
  }
}
"""

RATINGS_QUERY = """
query RatingsListQuery($count: Int!, $id: ID!, $courseFilter: String) {
  node(id: $id) {
    ... on Teacher {
      ratings(first: $count, courseFilter: $courseFilter) {
        edges {
          node {
            id
            comment
            date
            class
            helpfulRating
            difficultyRating
            attendanceMandatory
            wouldTakeAgain
            grade
            isForOnlineClass
            isForCredit
            ratingTags
            thumbsUpTotal
            thumbsDownTotal
            textbookUse
          }
        }
      }
    }
  }
}
"""
# Note: Added 'textbookUse' to query guess, will check if it works.
# If not I will remove it. 'textbookUse' is not in the original library query
# but might exist. Common field is 'textbookUsed' or similar.
# Actually, let's test without it first, or try to find the schema.
# I'll stick to safe fields first, then try to add 'textbookUse'.
# Based on some online sources, 'textbookUse' might be the field name (int 0-5 or similar?).
# But wait, looking at other scrapers, 'textbookUse' exists.

class RMPHelper:
    def __init__(self, professor_id):
        self.professor_id = str(professor_id)
        # The ID needs to be base64 encoded "Teacher-<ID>"
        self.b64_id = base64.b64encode(f"Teacher-{self.professor_id}".encode('ascii')).decode('ascii')

    def get_professor_details(self):
        payload = {
            "query": PROFESSOR_QUERY,
            "variables": {"id": self.b64_id}
        }
        try:
            response = requests.post(GRAPHQL_URL, json=payload, headers=HEADERS)
            response.raise_for_status()
            data = response.json()
            if data.get("errors"):
                logger.error(f"GraphQL Errors: {data['errors']}")
                return None
            return data["data"]["node"]
        except Exception as e:
            logger.error(f"Error fetching professor details: {e}")
            return None

    def get_reviews(self, count=10):
        # First try with textbookUse, if it fails, fallback without it
        query_with_textbook = RATINGS_QUERY

        payload = {
            "query": query_with_textbook,
            "variables": {
                "id": self.b64_id,
                "count": count,
                "courseFilter": None
            }
        }

        try:
            response = requests.post(GRAPHQL_URL, json=payload, headers=HEADERS)
            response.raise_for_status()
            data = response.json()

            if data.get("errors"):
                # Check if error is about textbookUse field
                errors = str(data['errors'])
                if "textbookUse" in errors:
                    logger.warning("textbookUse field not found, retrying without it.")
                    # Remove textbookUse from query
                    query_safe = RATINGS_QUERY.replace("textbookUse", "")
                    payload["query"] = query_safe
                    response = requests.post(GRAPHQL_URL, json=payload, headers=HEADERS)
                    response.raise_for_status()
                    data = response.json()
                else:
                    logger.error(f"GraphQL Errors: {data['errors']}")
                    return []

            if not data.get("data") or not data["data"].get("node"):
                return []

            edges = data["data"]["node"]["ratings"]["edges"]
            reviews = [edge["node"] for edge in edges]
            return reviews

        except Exception as e:
            logger.error(f"Error fetching reviews: {e}")
            return []

if __name__ == "__main__":
    # Test with Pengyuan Liu
    rmp = RMPHelper(2635703)
    print("Fetching Professor Details...")
    details = rmp.get_professor_details()
    print(json.dumps(details, indent=2))

    print("\nFetching Reviews...")
    reviews = rmp.get_reviews(count=5)
    print(json.dumps(reviews, indent=2))
