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
from rasa_sdk.events import SlotSet, ActionReverted, AllSlotsReset, FollowupAction
from requests.models import PreparedRequest

url = "http://localhost:8000/chatbox"
api_url = "http://localhost:8000/api"


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
        keywords = []

        # Search with category
        for entity in tracker.latest_message["entities"]:
            if entity["entity"] == "course_keyword":
                keywords.append(entity["value"])

        # Params for query
        params = {}
        if keywords is not None:
            params["keywords[]"] = keywords

        response = requests.get(f"{url}/courses", params=params)
        message = "Something went wrong!"
        recent_courses = []
        if response.ok:
            data = json.loads(response.content)
            if len(data["data"]) == 0:
                if keywords is not None:
                    message = "Sorry there is no courses for %s" % ', '.join(keywords)
                else:
                    message = "Sorry there is no such courses"
            else:
                c = ', '.join(keywords) + " " if keywords is not None else ""
                message = f"Here are some {c}courses for you: "
                recent_courses = data["data"][:3]
                message += ', '.join(data["data"][:3])

        req = PreparedRequest()
        req.prepare_url("http://localhost:8000/courses", params)

        json_message = {"text": message, "link": {"url": req.url, "title": "Show more"}}
        dispatcher.utter_message(json_message=json_message)

        return [SlotSet("recent_courses", recent_courses)]


class ActionShowCourses(Action):

    def name(self) -> Text:
        return "action_show_courses"

    async def run(
            self, dispatcher, tracker: Tracker, domain: Dict[Text, Any],
    ) -> List[Dict[Text, Any]]:
        keywords = tracker.get_slot("course_keyword")
        if keywords is not None and not isinstance(keywords, list):
            # noinspection PyTypeChecker
            keywords = list(keywords)
        params = {"keywords[]": keywords}
        req = PreparedRequest()
        req.prepare_url("http://localhost:8000/courses", params)
        json_message = {"text": "Here you are", "redirect": {"url": req.url}}

        dispatcher.utter_message(json_message=json_message)

        return []


class GetAccess(Action):

    async def run(self, dispatcher, tracker: Tracker, domain) -> List[
        Dict[Text, Any]]:
        user = tracker.get_slot("email")
        password = tracker.get_slot("password")
        if user is None or password is None:
            return [FollowupAction("login_form")]
        results = requests.post(f"{api_url}/login",
                                data={'email': user, 'password': password})
        if not results.ok:
            dispatcher.utter_message("Please enter valid information")
            return [ActionReverted(), AllSlotsReset()]

        response = json.loads(results.content)
        if not response["success"]:
            dispatcher.utter_message("These credentials do not match our records.")
            return [ActionReverted(), AllSlotsReset()]

        json_res = json.loads(results.content)
        name = json_res["data"]["name"]
        # personal access token for later request
        access_token = json_res["data"]["token"]

        pending_action = tracker.get_slot("pending_action")
        if pending_action is not None:
            if pending_action == EnrollCourse.get_name():
                # Enroll course
                # Do not call followup action or it will cause violence with rules
                res = EnrollCourse.enroll(dispatcher, tracker, access_token)
                return [SlotSet("access_token", access_token), SlotSet("name", name), SlotSet("pending_action", None),
                        *res]

            return [SlotSet("access_token", access_token), SlotSet("name", name), FollowupAction(pending_action)]

        template = "utter_access"
        if access_token is not None:
            template = "utter_already_login"
        dispatcher.utter_message(response=template)
        return [SlotSet("access_token", access_token), SlotSet("name", name)]

    def name(self):
        return 'action_get_access'


class EnrollCourse(Action):

    async def run(self, dispatcher, tracker: Tracker, domain) -> List[
        Dict[Text, Any]]:
        return self.enroll(dispatcher, tracker)

    def name(self):
        return self._name()

    @staticmethod
    def _name():
        return 'action_enroll_course'

    @staticmethod
    def get_name():
        return EnrollCourse._name()

    @staticmethod
    def enroll(dispatcher, tracker: Tracker, access_token=None):
        # Not login yet, save pending action and login to continue
        access_token = access_token or tracker.get_slot("access_token")
        if access_token is None:
            return [SlotSet("pending_action", EnrollCourse._name()), FollowupAction('login_form')]

        # Get the course name user have chosen
        course_name = tracker.get_slot("likely_course") or tracker.get_slot("course_name")
        if course_name is None:
            recent_courses = tracker.get_slot('recent_courses')
            if recent_courses is None or len(recent_courses) == 0:
                return [FollowupAction("utter_enroll_failed")]
            course_name = recent_courses[0]

        # Enroll course
        results = EnrollCourse._enroll(course_name, access_token)

        response = json.loads(results.content)
        # Failed
        if not results.ok or not response["success"]:
            if response["extras"] is not None and len(response["extras"]) > 0:
                likely_course = response["extras"][0]
                dispatcher.utter_message(
                    text=f"This course not exist on our website. Did you mean {likely_course}")
                return [SlotSet("likely_course", likely_course)]
            dispatcher.utter_message(response="utter_enroll_failed")
            return []

        template = "utter_enroll_succeed"
        dispatcher.utter_message(response=template)
        return []

    @staticmethod
    def _enroll(course_name, access_token):
        # Get the course name user have chosen
        if course_name is None:
            return None

        # Enroll course request
        headers = {'Accept': 'application/json',
                   'Authorization': f'Bearer {access_token}'}
        results = requests.post(f"{api_url}/courses/enroll",
                                data={'course_name': course_name},
                                headers=headers)
        return results
