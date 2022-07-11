# This files contains your custom actions which can be used to run
# custom Python code.
#
# See this guide on how to implement these action:
# https://rasa.com/docs/rasa/custom-actions


# This is a simple example for a custom action which utters "Hello World!"

import json
from typing import Any, Text, Dict, List

import requests
from rasa_sdk import Action, Tracker

url = "http://localhost:8000/chatbox"


#
#
# class ActionHelloWorld(Action):
#
#     def name(self) -> Text:
#         return "action_hello_world"
#
#     def run(self, dispatcher: CollectingDispatcher,
#             tracker: Tracker,
#             domain: Dict[Text, Any]) -> List[Dict[Text, Any]]:
#
#         dispatcher.utter_message(text="Hello World!")
#
#         return []

class ActionCheckCourses(Action):

    def name(self) -> Text:
        return "action_check_courses"

    async def run(
            self, dispatcher, tracker: Tracker, domain: Dict[Text, Any],
    ) -> List[Dict[Text, Any]]:
        category = None

        # Search with category
        for entity in tracker.latest_message["entities"]:
            if entity["entity"] == "course_category":
                category = entity["value"]

        # Params for query
        params = {}
        if category is not None:
            params["cats[]"] = [category]

        response = requests.get(f"{url}/courses", params=params)
        message = "Something went wrong!"
        if response.ok:
            data = json.loads(response.content)
            if len(data["data"]) == 0:
                if category is not None:
                    message = "Sorry there is no courses for %s" % category
                else:
                    message = "Sorry there is no such courses"
            else:
                c = category + " " if category is not None else ""
                message = f"Here are some {c}courses for you: "
                message += ', '.join(list(map(lambda x: x["name"], data["data"][:3])))

        json_message = {"text": message, "link": {"url": "http://localhost:8000/courses", "title": "Show more"}}
        dispatcher.utter_message(json_message=json_message)

        return []


class ActionShowCourses(Action):

    def name(self) -> Text:
        return "action_show_courses"

    async def run(
            self, dispatcher, tracker: Tracker, domain: Dict[Text, Any],
    ) -> List[Dict[Text, Any]]:
        json_message = {"text": "Here you are", "redirect": {"url": "http://localhost:8000/courses"}}

        dispatcher.utter_message(json_message=json_message)

        return []

# tracker = SQLTrackerStore(host='postgres', username='rasa', password='rasa-chatbox', db='rasa', dialect='postgresql')
