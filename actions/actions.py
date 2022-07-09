# This files contains your custom actions which can be used to run
# custom Python code.
#
# See this guide on how to implement these action:
# https://rasa.com/docs/rasa/custom-actions


# This is a simple example for a custom action which utters "Hello World!"

from typing import Any, Text, Dict, List

from rasa_sdk import Action, Tracker
from rasa_sdk.executor import CollectingDispatcher

import requests
import json

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
        response = requests.get(f"{url}/courses")
        message = "Here are some courses for you: "
        if response.ok:
            data = json.loads(response.content)
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
        response = requests.post(f"{url}/show-courses")

        return []
