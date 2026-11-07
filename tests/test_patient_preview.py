from pathlib import Path
from tempfile import TemporaryDirectory
import re
import unittest

from app import create_app


class PatientPreviewTestCase(unittest.TestCase):
    def setUp(self):
        self.temp=TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.app=create_app("testing",instance_path=self.temp.name)
        self.client=self.app.test_client()

    def test_female_profile_image_and_address_are_consistent(self):
        page=self.client.get("/preview/room?patient=female").get_data(as_text=True)
        for value in ("Trần Ngọc Linh","patient-female.png","28 tuổi · Nữ","Chị bắt đầu",'data-patient-key="female"','data-patient-initials="NL"'):
            self.assertIn(value,page)
        self.assertNotIn('filename=patient',page)
        self.assertEqual(self.client.get("/preview/room?patient=unknown").status_code,404)
        response=self.client.get("/static/images/patient-female.png")
        self.assertEqual(response.status_code,200)
        response.close()

    def test_api_keeps_patient_responses_separate(self):
        page=self.client.get("/preview/room?patient=female").get_data(as_text=True)
        token=re.search(r'name="csrf-token" content="([^"]+)"',page).group(1)
        headers={"X-CSRFToken":token}
        for key,expected in [("male","sáng nay"),("female","đầu tuần này")]:
            res=self.client.post("/api/v1/preview/messages",headers=headers,json={"text":"Bắt đầu từ khi nào?","patient_key":key})
            self.assertEqual(res.status_code,200)
            self.assertIn(expected,res.get_json()["data"]["text"])
        for invalid in ("../.env",[],{},None):
            res=self.client.post("/api/v1/preview/messages",headers=headers,json={"text":"Chào","patient_key":invalid})
            self.assertEqual(res.status_code,400)
        self.assertEqual(list(Path(self.temp.name).glob("*.sqlite")),[])

    def test_private_case_files_and_rubric_are_not_served(self):
        for path in ("/data/cases/mq_com_01_v1.json","/static/data/cases/mq_com_01_v1.json","/admin/cases"):
            self.assertEqual(self.client.get(path).status_code,404)
        self.assertEqual(self.client.get("/cases").status_code,302)
        page=self.client.get("/preview/room?patient=female").get_data(as_text=True)
        self.assertNotIn("Lo không hoàn thành phần việc đã nhận",page)
        self.assertNotIn("cooperation",page)
        self.assertNotIn("criterion_code",page)
