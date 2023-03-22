# This files contains your custom actions which can be used to run
# custom Python code.
#
# See this guide on how to implement these action:
# https://rasa.com/docs/rasa/custom-actions


# This is a simple example for a custom action which utters "Hello World!"

import json
from abc import ABC, abstractmethod
from typing import Any, Text, Dict, List

import requests
from rasa_sdk import Action, Tracker
from rasa_sdk.events import SlotSet, ActionReverted, AllSlotsReset, FollowupAction
from requests.models import PreparedRequest

base_url = "https://ilearning.fly.dev"
api_url = "https://ilearning.fly.dev/api"

map_resource_types_to_uri = {'category': 'category', 'language': 'language', 'code': 'programming-language'}
map_resource_types_to_plural_uri = {'category': 'categories', 'language': 'languages', 'code': 'programming-languages'}


class PendingAction(Action, ABC):

    @staticmethod
    @abstractmethod
    def perform(dispatcher, tracker: Tracker, domain=None, access_token=None, **kwargs):
        raise NotImplementedError("An pending action must implement perform")

    @staticmethod
    @abstractmethod
    def condition(tracker: Tracker, **kwargs):
        raise NotImplementedError("An pending action must implement condition method")

    @staticmethod
    @abstractmethod
    def get_name():
        raise NotImplementedError("An pending action must implement get_name method")


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

        response = requests.get(f"{api_url}/courses", params=params)
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
                recent_courses = list(map(lambda x: x["name"], data["data"][:3]))
                message += ', '.join(list(map(lambda x: x["name"], data["data"][:3])))

        req = PreparedRequest()
        req.prepare_url(f"{base_url}/courses", params)

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
        req.prepare_url(f"{base_url}/courses", params)
        json_message = {"text": "Here you are", "redirect": {"url": req.url}}

        dispatcher.utter_message(json_message=json_message)

        return []


class ActionRegister(Action):

    async def run(self, dispatcher, tracker: Tracker, domain) -> List[
        Dict[Text, Any]]:
        username = tracker.get_slot("username")
        email = tracker.get_slot("email")
        password = tracker.get_slot("password")

        if email is None or password is None:
            return [FollowupAction("utter_not_enough_info")]
        results = requests.post(f"{api_url}/register",
                                data={"username": username, 'email': email, 'password': password,
                                      "password_confirmation": password})
        if not results.ok:
            # Do not return as follow-up action or will contradict the rule
            dispatcher.utter_message(response="utter_register_failed")
            return []

        json_res = json.loads(results.content)
        name = json_res["data"]["name"]
        # personal access token for later request
        access_token = json_res["data"]["token"]

        template = "utter_register_succeed"
        dispatcher.utter_message(response=template)
        return [SlotSet("access_token", access_token), SlotSet("name", name)]

    def name(self):
        return 'action_register'


class EnrollCourse(PendingAction):

    async def run(self, dispatcher, tracker: Tracker, domain) -> List[
        Dict[Text, Any]]:
        return self.perform(dispatcher, tracker)

    def name(self):
        return self._name()

    @staticmethod
    def _name():
        return 'action_enroll_course'

    @staticmethod
    def get_name():
        return EnrollCourse._name()

    @staticmethod
    def perform(dispatcher, tracker: Tracker, domain=None, access_token=None, **kwargs):
        # Get the course name user have chosen
        course_name = tracker.get_slot("likely_course") or tracker.get_slot("course_name")
        if course_name is None:
            recent_courses = tracker.get_slot('recent_courses')
            if recent_courses is None or len(recent_courses) == 0:
                return [FollowupAction("utter_enroll_failed")]
            course_name = recent_courses[0]
        # Check if is valid course
        data = json.loads(requests.get(f"{api_url}/similar-courses", params={"course_name": course_name}).content)[
            "data"]
        if data["course"] is None:
            if data["extras"] is not None and len(data["extras"]) > 0:
                likely_course = data["extras"][0]["name"]
                return [SlotSet("likely_course", likely_course), FollowupAction("utter_course_not_found_and_suggest")]

            return [FollowupAction("utter_course_not_found")]

        if data["course"]["price"] is not None and data["course"]["price"] > 0:
            return [FollowupAction("utter_ask_buy_course")]

        # Not login yet, save pending action and login to continue
        access_token = access_token or tracker.get_slot("access_token")
        if access_token is None:
            return [SlotSet("pending_action", EnrollCourse._name()), FollowupAction('login_form')]

        # Enroll course
        results = EnrollCourse._perform(course_name, access_token)

        response = json.loads(results.content)
        # Failed
        if not results.ok or not response["success"]:
            if response["extras"] is not None and len(response["extras"]) > 0:
                likely_course = response["extras"][0]["name"]
                dispatcher.utter_message(
                    text=f"This course not exist on our website. Did you mean {likely_course}")
                return [SlotSet("likely_course", likely_course)]
            dispatcher.utter_message(response="utter_enroll_failed")
            return []

        template = "utter_enroll_succeed"
        dispatcher.utter_message(response=template)
        return [FollowupAction("action_listen")]

    @staticmethod
    def _perform(course_name, access_token):
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

    @staticmethod
    def condition(tracker, **kwargs):
        access_token = kwargs.get("access_token", None)
        condition = (access_token or tracker.get_slot("access_token")) is not None
        return condition, "OK" if condition else "Need to login"


class ActionDetailCourse(Action):

    async def run(self, dispatcher, tracker: Tracker, domain) -> List[
        Dict[Text, Any]]:
        # Get the course name user have chosen
        course_name = tracker.get_slot("likely_course") or tracker.get_slot("course_name")
        if course_name is None:
            recent_courses = tracker.get_slot('recent_courses')
            if recent_courses is None or len(recent_courses) == 0:
                return [FollowupAction("utter_please_choose_course")]
            course_name = recent_courses[0]
        # Check if is valid course
        data = json.loads(requests.get(f"{api_url}/similar-courses", params={"course_name": course_name}).content)[
            "data"]
        if data["course"] is None:
            if data["extras"] is not None and len(data["extras"]) > 0:
                likely_course = data["extras"][0]["name"]
                return [SlotSet("likely_course", likely_course), FollowupAction("utter_course_not_found_and_suggest")]

            return [FollowupAction("utter_course_not_found")]

        req = PreparedRequest()
        req.prepare_url(f"{base_url}/courses/{data['course']['id']}", {})
        json_message = {"text": "Here you are", "redirect": {"url": req.url}}

        dispatcher.utter_message(json_message=json_message)
        return []

    def name(self):
        return "action_detail_course"


class ActionBuyCourse(Action):
    def name(self) -> Text:
        return 'action_buy_course'

    async def run(self, dispatcher, tracker: Tracker, domain):
        # Get the course name user have chosen
        course_name = tracker.get_slot("likely_course") or tracker.get_slot("course_name")
        if course_name is None:
            recent_courses = tracker.get_slot('recent_courses')
            if recent_courses is None or len(recent_courses) == 0:
                return [FollowupAction("utter_enroll_failed")]
            course_name = recent_courses[0]
        # Check if is valid course
        data = json.loads(requests.get(f"{api_url}/similar-courses", params={"course_name": course_name}).content)[
            "data"]
        if data["course"] is None:
            if data["extras"] is not None and len(data["extras"]) > 0:
                likely_course = data["extras"][0]["name"]
                return [SlotSet("likely_course", likely_course), FollowupAction("utter_course_not_found_and_suggest")]

            return [FollowupAction("utter_course_not_found")]

        req = PreparedRequest()
        req.prepare_url(f"{base_url}/courses/checkout/{data['course']['id']}", {})
        json_message = {"text": "Please fill the require field and pay to enroll the course",
                        "redirect": {"url": req.url}}

        dispatcher.utter_message(json_message=json_message)
        return []


class ActionShowMyCourses(PendingAction):

    def name(self) -> Text:
        return self._name()

    @staticmethod
    def _name():
        return 'action_show_my_courses'

    @staticmethod
    def get_name():
        return ActionShowMyCourses._name()

    async def run(
            self, dispatcher, tracker: Tracker, domain: Dict[Text, Any],
    ) -> List[Dict[Text, Any]]:
        return self.perform(dispatcher, tracker, domain)

    # noinspection PyUnusedLocal
    @staticmethod
    def perform(dispatcher, tracker, domain=None, access_token=None, **kwargs):
        # Not login yet, save pending action and login to continue
        access_token = access_token or tracker.get_slot("access_token")
        if access_token is None:
            return [SlotSet("pending_action", ActionShowMyCourses._name()), FollowupAction('login_form')]

        keywords = []
        # Search with category
        for entity in tracker.latest_message["entities"]:
            if entity["entity"] == "course_keyword":
                keywords.append(entity["value"])

        # Params for query
        params = {}
        if keywords is not None:
            params["keywords[]"] = keywords

        headers = {'Accept': 'application/json',
                   'Authorization': f'Bearer {access_token}'}
        response = requests.get(f"{api_url}/courses/my-courses", headers=headers)
        message = "Something went wrong!"
        recent_courses = []
        if response.ok:
            data = json.loads(response.content)
            if len(data["data"]) == 0:
                if keywords is not None:
                    message = "Sorry you have not enroll any course of %s" % ', '.join(keywords)
                else:
                    message = "Sorry you have not enroll any course yet"
            else:
                c = ', '.join(keywords) + " " if keywords is not None else ""
                message = f"Here are some of your {c}courses: "
                recent_courses = list(map(lambda x: x["name"], data["data"][:3]))
                message += ', '.join(list(map(lambda x: x["name"], data["data"][:3])))

        req = PreparedRequest()
        req.prepare_url(f"{base_url}/student/courses", params)

        json_message = {"text": message, "link": {"url": req.url, "title": "Show more"}}
        dispatcher.utter_message(json_message=json_message)

        return [SlotSet("recent_courses", recent_courses)]

    @staticmethod
    def condition(tracker, **kwargs):
        access_token = kwargs.get("access_token", None)
        condition = (access_token or tracker.get_slot("access_token")) is not None
        return condition, "OK" if condition else "Need to login"


class ActionShowProgressCourse(PendingAction):

    def name(self) -> Text:
        return self._name()

    @staticmethod
    def _name():
        return 'action_show_progress_course'

    @staticmethod
    def get_name():
        return ActionShowProgressCourse._name()

    async def run(
            self, dispatcher, tracker: Tracker, domain: Dict[Text, Any],
    ) -> List[Dict[Text, Any]]:
        return self.perform(dispatcher, tracker, domain)

    # noinspection PyUnusedLocal
    @staticmethod
    def perform(dispatcher, tracker, domain=None, access_token=None, **kwargs):
        # Not login yet, save pending action and login to continue
        access_token = access_token or tracker.get_slot("access_token")
        if access_token is None:
            return [SlotSet("pending_action", ActionShowProgressCourse._name()), FollowupAction('login_form')]

        valid, course = check_valid_course(tracker)
        if not valid:
            if course is not None:
                return [SlotSet("likely_course", course['name']),
                        FollowupAction("utter_course_not_found_and_suggest")]
            return [FollowupAction("utter_course_not_found")]

        params = {"course_id": course["id"]}

        headers = {'Accept': 'application/json',
                   'Authorization': f'Bearer {access_token}'}
        response = requests.get(f"{api_url}/courses/progress", params=params, headers=headers)
        message = "Something went wrong!"
        recent_courses = []
        if response.ok:
            data = json.loads(response.content)["data"]
            progress = 100.0 * data["complete"] / data["total"]
            if progress == 0:
                message = "You have not start learning the course yet"
            else:
                message = f"You have complete {round(progress)}% of the course"

        req = PreparedRequest()
        req.prepare_url(f"{base_url}/student/courses", {})

        json_message = {"text": message, "link": {"url": req.url, "title": "Show more"}}
        dispatcher.utter_message(json_message=json_message)

        return []

    @staticmethod
    def condition(tracker, **kwargs):
        access_token = kwargs.get("access_token", None)
        condition = (access_token or tracker.get_slot("access_token")) is not None
        return condition, "OK" if condition else "Need to login"


class ActionShowPendingCourses(PendingAction):

    def name(self) -> Text:
        return self._name()

    @staticmethod
    def _name():
        return 'action_show_pending_courses'

    @staticmethod
    def get_name():
        return ActionShowPendingCourses._name()

    async def run(
            self, dispatcher, tracker: Tracker, domain: Dict[Text, Any],
    ) -> List[Dict[Text, Any]]:
        return self.perform(dispatcher, tracker, domain)

    # noinspection PyUnusedLocal
    @staticmethod
    def perform(dispatcher, tracker, domain=None, access_token=None, **kwargs):
        # Not login yet, save pending action and login to continue
        check, message = ActionShowPendingCourses.condition(tracker, access_token=access_token)
        if not check:
            dispatcher.utter_message(message)
            return [SlotSet("pending_action", ActionShowPendingCourses._name()), FollowupAction('login_form')]

        access_token = access_token or tracker.get_slot("access_token")
        headers = {'Accept': 'application/json',
                   'Authorization': f'Bearer {access_token}'}
        response = requests.get(f"{api_url}/courses/pending", headers=headers)
        message = "Something went wrong!"
        recent_courses = []
        table_data = []
        if response.ok:
            data = json.loads(response.content)
            if len(data["data"]) == 0:
                message = "Sorry there is no pending course"
            else:
                url = f"{base_url}/courses/%s"
                table_data = list(
                    map(lambda x: [
                        [{"data": x["name"], "class": ""}],
                        [
                            {"data": "View", "class": "text-center", "link": f"{base_url}/courses/{x['id']}"},
                            {"data": "Approve", "class": "text-center text-green",
                             "json_payload": json.dumps(
                                 {"sender": tracker.sender_id,
                                  "message": f"/approve_course{{\"course_name\": \"{x['name']}\"}}"})}
                        ]
                    ],
                        data["data"]))
                recent_courses = list(map(lambda x: x["name"], data["data"]))
                message = f"Here are list of pending courses: "

        json_message = {"text": message,
                        "table": {"headers": [{"data": "Name", "class": ""}, {"data": "Action", "class": ""}],
                                  "data": table_data}}
        dispatcher.utter_message(json_message=json_message)

        return [SlotSet("recent_courses", recent_courses)]

    @staticmethod
    def condition(tracker, **kwargs):
        access_token = kwargs.get("access_token", None)
        condition = is_admin(tracker, access_token)
        return condition, "OK" if condition else "Need to login into admin account"


class ActionApproveCourse(PendingAction):

    async def run(self, dispatcher, tracker: Tracker, domain) -> List[
        Dict[Text, Any]]:
        return self.perform(dispatcher, tracker)

    def name(self):
        return self._name()

    @staticmethod
    def _name():
        return 'action_approve_course'

    @staticmethod
    def get_name():
        return ActionApproveCourse._name()

    @staticmethod
    def perform(dispatcher, tracker: Tracker, domain=None, access_token=None, **kwargs):
        # Get the course name user have chosen
        course_name = tracker.get_slot("likely_course") or tracker.get_slot("course_name")
        if course_name is None:
            recent_courses = tracker.get_slot('recent_courses')
            if recent_courses is None or len(recent_courses) == 0:
                return [FollowupAction("utter_enroll_failed")]
            course_name = recent_courses[0]
        # Check if is valid course
        data = json.loads(requests.get(f"{api_url}/similar-courses", params={"course_name": course_name}).content)[
            "data"]
        if data["course"] is None:
            if data["extras"] is not None and len(data["extras"]) > 0:
                likely_course = data["extras"][0]["name"]
                return [SlotSet("likely_course", likely_course), FollowupAction("utter_course_not_found_and_suggest")]

            return [FollowupAction("utter_course_not_found")]

        # Not login yet, save pending action and login to continue
        access_token = access_token or tracker.get_slot("access_token")
        if access_token is None:
            return [SlotSet("pending_action", ActionApproveCourse._name()), FollowupAction('login_form')]

        # Enroll course
        results = ActionApproveCourse._perform(data["course"]["id"], access_token)

        response = json.loads(results.content)
        # Failed
        if not results.ok or not response["success"]:
            dispatcher.utter_message(response="utter_approve_failed")
            return []

        template = "utter_approve_succeed"
        dispatcher.utter_message(response=template)
        return [FollowupAction("action_listen")]

    @staticmethod
    def _perform(course_id, access_token):
        # Get the course name user have chosen
        if course_id is None:
            return None

        # Enroll course request
        headers = {'Accept': 'application/json',
                   'Authorization': f'Bearer {access_token}'}
        results = requests.put(f"{api_url}/courses/approve",
                               data={'course_id': course_id},
                               headers=headers)
        return results

    @staticmethod
    def condition(tracker, **kwargs):
        access_token = kwargs.get("access_token", None)
        condition = is_admin(tracker, access_token)
        return condition, "OK" if condition else "Need to login into admin account"


class ActionAddResource(PendingAction):

    async def run(self, dispatcher, tracker: Tracker, domain) -> List[
        Dict[Text, Any]]:
        return self.perform(dispatcher, tracker)

    def name(self):
        return self._name()

    @staticmethod
    def _name():
        return 'action_add_resource'

    @staticmethod
    def get_name():
        return ActionAddResource._name()

    @staticmethod
    def perform(dispatcher, tracker: Tracker, domain=None, access_token=None, **kwargs):
        # Not login yet, save pending action and login to continue
        access_token = access_token or tracker.get_slot("access_token")
        check, message = ActionAddResource.condition(tracker, access_token=access_token)
        if not check:
            dispatcher.utter_message(message)
            return [SlotSet("pending_action", ActionAddResource.get_name()), FollowupAction('login_form')]

        resource_type = map_resource_types_to_uri.get(tracker.get_slot("resource_type"), None)
        # Get the course name user have chosen
        resource_name = tracker.get_slot("likely_resource") or tracker.get_slot("resource_name")
        if resource_name is None or resource_type is None:
            if tracker.get_slot("active_loop") is None:
                return [FollowupAction("resource_form")]
            dispatcher.utter_message(response='utter_not_enough_info')
            return []
        # Add category
        results = ActionAddResource._perform(resource_type, resource_name, access_token)

        response = json.loads(results.content)
        # Failed
        if not results.ok or not response["success"]:
            dispatcher.utter_message(response="utter_failed")
            return []

        template = "utter_succeed"
        dispatcher.utter_message(response=template)
        return [FollowupAction("action_listen")]

    @staticmethod
    def _perform(resource_type, name, access_token):
        # Get the course name user have chosen
        if name is None:
            return None

        # Enroll course request
        headers = {'Accept': 'application/json',
                   'Authorization': f'Bearer {access_token}'}
        results = requests.post(f"{api_url}/admin/{resource_type}",
                                data={'name': name},
                                headers=headers)
        return results

    @staticmethod
    def condition(tracker, **kwargs):
        access_token = kwargs.get("access_token", None)
        condition = is_admin(tracker, access_token)
        return condition, "OK" if condition else "Need to login into admin account"


class ActionDeleteResource(PendingAction):

    async def run(self, dispatcher, tracker: Tracker, domain) -> List[
        Dict[Text, Any]]:
        return self.perform(dispatcher, tracker)

    def name(self):
        return self._name()

    @staticmethod
    def _name():
        return 'action_delete_resource'

    @staticmethod
    def get_name():
        return ActionDeleteResource._name()

    @staticmethod
    def perform(dispatcher, tracker: Tracker, domain=None, access_token=None, **kwargs):
        # Not login yet, save pending action and login to continue
        access_token = access_token or tracker.get_slot("access_token")
        check, message = ActionDeleteResource.condition(tracker, access_token=access_token)
        if not check:
            dispatcher.utter_message(message)
            return [SlotSet("pending_action", ActionDeleteResource.get_name()), FollowupAction('login_form')]
        resource_type = map_resource_types_to_uri.get(tracker.get_slot("resource_type"), None)
        # Get the course name user have chosen
        resource_name = tracker.get_slot("likely_resource") or tracker.get_slot("resource_name")
        if resource_name is None or resource_type is None:
            if tracker.get_slot("active_loop") is None:
                return [FollowupAction("resource_form")]
            dispatcher.utter_message(response='utter_not_enough_info')
            return []
        headers = {'Accept': 'application/json',
                   'Authorization': f'Bearer {access_token}'}
        # Check if is valid course
        data = json.loads(
            requests.get(f"{api_url}/admin/{resource_type}/similar", params={"name": resource_name},
                         headers=headers).content)
        data = data["data"]
        if data["resource"] is None:
            if data["extras"] is not None and len(data["extras"]) > 0:
                likely_category = data["extras"][0]["name"]
                # For generalize use resource instead specific model type
                return [SlotSet("resource_not_found", resource_name), SlotSet("likely_resource", likely_category),
                        FollowupAction("utter_resource_not_found_and_suggest")]

            return [SlotSet("resource_not_found", resource_name), FollowupAction("utter_resource_not_found")]

        # Enroll course
        results = ActionDeleteResource._perform(resource_type, resource_name, access_token)

        response = json.loads(results.content)
        # Failed
        if not results.ok or not response["success"]:
            dispatcher.utter_message(response="utter_failed")
            return []

        template = "utter_succeed"
        dispatcher.utter_message(response=template)
        return [FollowupAction("action_listen")]

    @staticmethod
    def _perform(resource_type, name, access_token):
        # Get the course name user have chosen
        if name is None:
            return None

        # Enroll course request
        headers = {'Accept': 'application/json',
                   'Authorization': f'Bearer {access_token}'}
        results = requests.delete(f"{api_url}/admin/{map_resource_types_to_uri.get(resource_type)}",
                                  data={'name': name},
                                  headers=headers)
        return results

    @staticmethod
    def condition(tracker, **kwargs):
        access_token = kwargs.get("access_token", None)
        condition = is_admin(tracker, access_token)
        return condition, "OK" if condition else "Need to login into admin account"


class ActionShowResources(PendingAction):

    def name(self) -> Text:
        return self._name()

    @staticmethod
    def _name():
        return 'action_show_resources'

    @staticmethod
    def get_name():
        return ActionShowResources._name()

    async def run(
            self, dispatcher, tracker: Tracker, domain: Dict[Text, Any],
    ) -> List[Dict[Text, Any]]:
        return self.perform(dispatcher, tracker, domain)

    # noinspection PyUnusedLocal
    @staticmethod
    def perform(dispatcher, tracker, domain=None, access_token=None, **kwargs):
        # Not login yet, save pending action and login to continue
        check, message = ActionShowResources.condition(tracker, access_token=access_token)
        if not check:
            dispatcher.utter_message(message)
            return [SlotSet("pending_action", ActionShowResources._name()), FollowupAction('login_form')]

        resource_type = map_resource_types_to_uri.get(tracker.get_slot("resource_type"), None)
        resource_types = map_resource_types_to_plural_uri.get(tracker.get_slot("resource_type"), None)
        if resource_type is None:
            if tracker.get_slot("active_loop") is None:
                return [FollowupAction("resource_form")]
            dispatcher.utter_message(response='utter_not_enough_info')
            return []

        access_token = access_token or tracker.get_slot("access_token")
        headers = {'Accept': 'application/json',
                   'Authorization': f'Bearer {access_token}'}
        response = requests.get(f"{api_url}/admin/{resource_types}", headers=headers)
        message = "Something went wrong!"
        recent_resources = []
        table_data = []
        if response.ok:
            data = json.loads(response.content)
            if len(data["data"]) == 0:
                message = f"Sorry there is no {resource_types}"
            else:
                table_data = list(
                    map(lambda x: [
                        [{"data": x["name"], "class": ""}],
                        [
                            {"data": "Edit", "class": "text-center",
                             "json_payload": json.dumps(
                                 {"sender": tracker.sender_id,
                                  "message": f"/edit_resource{{\"resource_name\": \"{x['name']}\"}}"})},

                            {"data": "Delete", "class": "text-center text-red-600",
                             "json_payload": json.dumps(
                                 {"sender": tracker.sender_id,
                                  "message": f"/delete_resource{{\"resource_name\": \"{x['name']}\"}}"})}
                        ]
                    ],
                        data["data"]))
                recent_resources = list(map(lambda x: x["name"], data["data"]))
                message = f"Here are list of {resource_types}: "

        json_message = {"text": message,
                        "table": {"headers": [{"data": "Name", "class": ""}, {"data": "Action", "class": ""}],
                                  "data": table_data}}
        dispatcher.utter_message(json_message=json_message)

        return [SlotSet("recent_resources", recent_resources)]

    @staticmethod
    def condition(tracker, **kwargs):
        access_token = kwargs.get("access_token", None)
        condition = is_admin(tracker, access_token)
        return condition, "OK" if condition else "Need to login into admin account"


class ActionEditResource(PendingAction):

    async def run(self, dispatcher, tracker: Tracker, domain) -> List[
        Dict[Text, Any]]:
        return self.perform(dispatcher, tracker)

    def name(self):
        return self._name()

    @staticmethod
    def _name():
        return 'action_edit_resource'

    @staticmethod
    def get_name():
        return ActionEditResource._name()

    @staticmethod
    def perform(dispatcher, tracker: Tracker, domain=None, access_token=None, **kwargs):
        # Not login yet, save pending action and login to continue
        access_token = access_token or tracker.get_slot("access_token")
        check, message = ActionEditResource.condition(tracker, access_token=access_token)
        if not check:
            dispatcher.utter_message(message)
            return [SlotSet("pending_action", ActionEditResource.get_name()), FollowupAction('login_form')]
        # Get the course name user have chosen
        resource_type = map_resource_types_to_uri.get(tracker.get_slot("resource_type"), None)
        resource_name = tracker.get_slot("likely_resource") or tracker.get_slot("resource_name")
        if resource_name is None or resource_type is None:
            if tracker.get_slot("active_loop") is None:
                return [FollowupAction("edit_resource_form")]
            dispatcher.utter_message(response='utter_not_enough_info')
            return []
        headers = {'Accept': 'application/json',
                   'Authorization': f'Bearer {access_token}'}
        # Check if is valid course
        data = json.loads(
            requests.get(f"{api_url}/admin/{resource_type}/similar", params={"name": resource_name},
                         headers=headers).content)
        data = data["data"]
        if data["resource"] is None:
            if data["extras"] is not None and len(data["extras"]) > 0:
                likely_category = data["extras"][0]["name"]
                # For generalize use resource instead specific model type
                return [SlotSet("resource_not_found", resource_name), SlotSet("likely_resource", likely_category),
                        FollowupAction("utter_resource_not_found_and_suggest")]

            return [SlotSet("resource_not_found", resource_name), FollowupAction("utter_resource_not_found")]
        # Add category
        results = ActionEditResource._perform(resource_type, data["resource"]["id"],
                                              tracker.get_slot("new_resource_name"),
                                              access_token)

        response = json.loads(results.content)
        # Failed
        if not results.ok or not response["success"]:
            dispatcher.utter_message(response="utter_failed")
            return []

        template = "utter_succeed"
        dispatcher.utter_message(response=template)
        return [FollowupAction("action_listen")]

    @staticmethod
    def _perform(resource_type, resource_id, new_name, access_token):
        # Get the course name user have chosen
        if resource_id is None:
            return None

        # Enroll course request
        headers = {'Accept': 'application/json',
                   'Authorization': f'Bearer {access_token}'}
        results = requests.post(f"{api_url}/admin/{resource_type}",
                                data={'id': resource_id, 'name': new_name},
                                headers=headers)
        return results

    @staticmethod
    def condition(tracker, **kwargs):
        access_token = kwargs.get("access_token", None)
        condition = is_admin(tracker, access_token)
        return condition, "OK" if condition else "Need to login into admin account"


class ActionShowCourseStatistic(PendingAction):

    def name(self) -> Text:
        return self._name()

    @staticmethod
    def _name():
        return 'action_show_course_statistic'

    @staticmethod
    def get_name():
        return ActionShowCourseStatistic._name()

    async def run(
            self, dispatcher, tracker: Tracker, domain: Dict[Text, Any],
    ) -> List[Dict[Text, Any]]:
        return self.perform(dispatcher, tracker, domain)

    # noinspection PyUnusedLocal
    @staticmethod
    def perform(dispatcher, tracker, domain=None, access_token=None, **kwargs):
        # Not login yet, save pending action and login to continue
        check, message = ActionShowCourseStatistic.condition(tracker, access_token=access_token)
        if not check:
            dispatcher.utter_message(message)
            return [SlotSet("pending_action", ActionShowCourseStatistic._name()), FollowupAction('login_form')]

        access_token = access_token or tracker.get_slot("access_token")
        headers = {'Accept': 'application/json',
                   'Authorization': f'Bearer {access_token}'}
        response = requests.get(f"{api_url}/author/courses/statistic", headers=headers)
        message = "Something went wrong!"
        table_data = []
        if response.ok:
            data = json.loads(response.content)
            if len(data["data"]) == 0:
                message = f"Sorry you have not create any course yet"
            else:
                table_data = list(
                    map(lambda x: [
                        [{"data": x["name"], "class": ""}],
                        [{"data": default(x['earned'], 0), "class": "text-center"}],
                        [{"data": default(x['enroll'], 0), "class": "text-center"}],
                        [{"data": default(x['rating'], 'No rating'), "class": "text-center"}],
                    ],
                        data["data"]))
                message = f"Here are your courses statistic: "

        json_message = {"text": message,
                        "table": {
                            "headers": [{"data": "Name"}, {"data": "Earned", "class": "text-center"}, {"data": "Enroll", "class": "text-center"}, {"data": "Rating"}],
                            "data": table_data}}
        dispatcher.utter_message(json_message=json_message)

        return []

    @staticmethod
    def condition(tracker, **kwargs):
        access_token = kwargs.get("access_token", None)
        condition = is_author(tracker, access_token)
        return condition, "OK" if condition else "Need to login into author or admin account"


pending_action_class = [EnrollCourse, ActionShowMyCourses, ActionShowProgressCourse, ActionShowPendingCourses,
                        ActionApproveCourse, ActionAddResource, ActionDeleteResource, ActionEditResource,
                        ActionShowResources, ActionShowCourseStatistic]


class ActionAccessAndPerform(Action):

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
            # Not satisfy condition to perform pending action, keep login
            check, message = self.check_pending_action_condition(tracker, pending_action, access_token)
            if not check:
                dispatcher.utter_message(message)
                if tracker.get_slot("active_loop") is None:
                    return [FollowupAction("login_form")]
                # Reset form and login again into admin account
                return [SlotSet("active_loop", None), SlotSet("requested_slot", None), SlotSet("email", None),
                        SlotSet("password", None),
                        FollowupAction("login_form")]

            res = self.perform_pending_action(dispatcher, tracker, domain, access_token, pending_action)

            return [SlotSet("access_token", access_token), SlotSet("name", name), SlotSet("pending_action", None), *res]

        template = "utter_access"
        if access_token is not None:
            template = "utter_already_login"
        dispatcher.utter_message(response=template)
        return [SlotSet("access_token", access_token), SlotSet("name", name)]

    def name(self):
        return 'action_access_and_perform'

    @staticmethod
    def perform_pending_action(dispatcher, tracker, domain, access_token, pending_action):
        for action_cls in pending_action_class:
            if pending_action == action_cls.get_name():
                return action_cls.perform(dispatcher=dispatcher, tracker=tracker, domain=domain,
                                          access_token=access_token)
        return []

    @staticmethod
    def check_pending_action_condition(tracker, pending_action, access_token=None):
        for action_cls in pending_action_class:
            if pending_action == action_cls.get_name():
                return action_cls.condition(tracker=tracker, access_token=access_token)
        return False, "Invalid action"


def check_valid_course(tracker):
    """
    Check if a course name in tracker is valid
    :param tracker: tracker of conversation
    :return: bool, course (True and the course if valid and False, the likely course with similar name)
    """
    # Get the course name user have chosen
    course_name = tracker.get_slot("likely_course") or tracker.get_slot("course_name")
    if course_name is None:
        recent_courses = tracker.get_slot('recent_courses')
        if recent_courses is None or len(recent_courses) == 0:
            return False, None
        course_name = recent_courses[0]
    # Check if is valid course
    data = json.loads(requests.get(f"{api_url}/similar-courses", params={"course_name": course_name}).content)[
        "data"]
    if data["course"] is None:
        if data["extras"] is not None and len(data["extras"]) > 0:
            likely_course = data["extras"][0]
            return False, likely_course

        return False, None

    return True, data["course"]


def is_admin(tracker, access_token=None):
    """
    Check if a course name in tracker is valid
    :param tracker: tracker of conversation
    :param access_token: the token after login
    :return: bool, course (True and the course if valid and False, the likely course with similar name)
    """
    access_token = access_token or tracker.get_slot("access_token")
    if access_token is None:
        return False
    # Check if is valid course
    headers = {'Accept': 'application/json',
               'Authorization': f'Bearer {access_token}'}
    data = json.loads(requests.get(f"{api_url}/is-admin", headers=headers).content)["data"]
    if data:
        return True

    return False


def is_author(tracker, access_token=None):
    """
    Check if a course name in tracker is valid
    :param tracker: tracker of conversation
    :param access_token: the token after login
    :return: bool, course (True and the course if valid and False, the likely course with similar name)
    """
    access_token = access_token or tracker.get_slot("access_token")
    if access_token is None:
        return False
    # Check if is valid course
    headers = {'Accept': 'application/json',
               'Authorization': f'Bearer {access_token}'}
    data = json.loads(requests.get(f"{api_url}/is-author", headers=headers).content)["data"]
    if data:
        return True

    return False


def default(value, other):
    if value is not None:
        return value
    return other
