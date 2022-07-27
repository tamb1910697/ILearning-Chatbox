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

base_url = "http://127.0.0.1:8000"
api_url = "http://127.0.0.1:8000/api"


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
        if pending_action == EnrollCourse.get_name():
            # Enroll course
            # Do not call followup action, or it will cause violence with rules
            res = EnrollCourse.enroll(dispatcher, tracker, access_token)
            return res

        if pending_action == ActionShowMyCourses.get_name():
            res = ActionShowMyCourses.perform(dispatcher, tracker, domain, access_token)
            return res

        if pending_action == ActionShowProgressCourse.get_name():
            res = ActionShowProgressCourse.perform(dispatcher, tracker, domain, access_token)
            return res

        if pending_action == ActionShowPendingCourses.get_name():
            res = ActionShowPendingCourses.perform(dispatcher, tracker, domain, access_token)
            return res

        return []

    @staticmethod
    def check_pending_action_condition(tracker, pending_action, access_token=None):
        if pending_action == EnrollCourse.get_name():
            return EnrollCourse.condition(tracker, access_token)

        if pending_action == ActionShowMyCourses.get_name():
            return ActionShowMyCourses.condition(tracker, access_token)

        if pending_action == ActionShowProgressCourse.get_name():
            return ActionShowProgressCourse.condition(tracker, access_token)

        if pending_action == ActionShowPendingCourses.get_name():
            return ActionShowPendingCourses.condition(tracker, access_token)

        return False, "Invalid action"


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
        results = EnrollCourse._enroll(course_name, access_token)

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

    @staticmethod
    def condition(tracker, access_token=None):
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


class ActionShowMyCourses(Action):

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
    def perform(dispatcher, tracker, domain=None, access_token=None):
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
    def condition(tracker, access_token=None):
        condition = (access_token or tracker.get_slot("access_token")) is not None
        return condition, "OK" if condition else "Need to login"


class ActionShowProgressCourse(Action):

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
    def perform(dispatcher, tracker, domain=None, access_token=None):
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
    def condition(tracker, access_token=None):
        condition = (access_token or tracker.get_slot("access_token")) is not None
        return condition, "OK" if condition else "Need to login"


# class ActionAdminAccessAndPerform(Action):
# 
#     async def run(self, dispatcher, tracker: Tracker, domain) -> List[
#         Dict[Text, Any]]:
#         if is_admin(tracker):
#             access_token = tracker.get_slot("access_token")
#             pending_action = tracker.get_slot("pending_action")
#             if pending_action is not None:
#                 res = self.perform_pending_action(dispatcher, tracker, domain, access_token, pending_action)
#                 return [SlotSet("pending_action", None), *res]
# 
#         user = tracker.get_slot("email")
#         password = tracker.get_slot("password")
#         if user is None or password is None:
#             return [FollowupAction("login_form")]
#         results = requests.post(f"{api_url}/login",
#                                 data={'email': user, 'password': password})
#         if not results.ok:
#             dispatcher.utter_message("Please enter valid information")
#             return [ActionReverted(), AllSlotsReset()]
# 
#         response = json.loads(results.content)
#         if not response["success"]:
#             dispatcher.utter_message("These credentials do not match our records.")
#             return [ActionReverted(), AllSlotsReset()]
# 
#         json_res = json.loads(results.content)
#         name = json_res["data"]["name"]
#         # personal access token for later request
#         access_token = json_res["data"]["token"]
#         # Not admin account return
#         if not is_admin(tracker):
#             dispatcher.utter_message(response="utter_not_admin")
#             return []
# 
#         pending_action = tracker.get_slot("pending_action")
#         if pending_action is not None:
#             res = self.perform_pending_action(dispatcher, tracker, domain, access_token, pending_action)
#             return [SlotSet("access_token", access_token), SlotSet("name", name), SlotSet("pending_action", None), *res]
# 
#         template = "utter_access"
#         if access_token is not None:
#             template = "utter_already_login"
#         dispatcher.utter_message(response=template)
#         return [SlotSet("access_token", access_token), SlotSet("name", name)]
# 
#     def name(self):
#         return 'action_access_and_perform'


class ActionShowPendingCourses(Action):

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
    def perform(dispatcher, tracker, domain=None, access_token=None):
        # Not login yet, save pending action and login to continue
        check, message = ActionShowPendingCourses.condition(tracker, access_token)
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
                    map(lambda x: [{"data": x["name"], "class": ""}, {"data": "View", "class": "text-center", "link": f"{base_url}/courses/{x['id']}"}], data["data"]))
                recent_courses = list(map(lambda x: x["name"], data["data"]))
                message = f"Here are list of pending courses: "

        json_message = {"text": message,
                        "table": {"headers": [{"data": "Name", "class": ""}, {"data": "Action", "class": ""}],
                                  "data": table_data}}
        dispatcher.utter_message(json_message=json_message)

        return [SlotSet("recent_courses", recent_courses)]

    @staticmethod
    def condition(tracker, access_token=None):
        condition = is_admin(tracker, access_token)
        return condition, "OK" if condition else "Need to login into admin account"


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
