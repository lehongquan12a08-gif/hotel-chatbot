import os
import gspread
from google.oauth2.service_account import Credentials

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CREDS_PATH = os.path.join(BASE_DIR, "service_account.json")

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive"
]

def save_booking(data):
    creds = Credentials.from_service_account_file(
        CREDS_PATH,
        scopes=SCOPES
    )

    client = gspread.authorize(creds)

    sheet = client.open("EDEN Bookings").sheet1

    sheet.append_row([
        data.get("checkin"),
        data.get("checkout"),
        data.get("room"),
        data.get("guests"),
        data.get("name"),
        data.get("phone")
    ])
