import os, json, gspread
from google.oauth2.service_account import Credentials

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive"
]

def save_booking(data):
    service_account_info = json.loads(
        os.environ["GOOGLE_SERVICE_ACCOUNT_JSON"]
    )

    creds = Credentials.from_service_account_info(
        service_account_info,
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
