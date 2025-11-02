import os.path
import configparser
import sys
import logging

# from google.auth.transport.requests import Request
# from google.oauth2.credentials import Credentials
# from google_auth_oauthlib.flow import InstalledAppFlow
# from googleapiclient.discovery import build
# from googleapiclient.errors import HttpError

import gspread
from gspread.exceptions import APIError
from helpers import load_config

# Initialize logging (console only)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler()]
)
logger = logging.getLogger(__name__)

config = load_config("config.ini")

SCOPES = [config.get("sheets", "scopes")]
SPREADSHEET_ID = config.get("sheets", "spreadsheet_id")
RANGE_NAME = config.get("sheets", "range_name")
WORKSHEET_NAME = config.get("sheets", "worksheet_name", fallback="Repeaters")
CREDENTIALS_FILE = config.get("sheets", "credentials_file", fallback="creds.json")


# def get_credentials():
#   Get Google Sheets API credentials, handling authentication flow if needed.
#     Credentials: Valid Google Sheets API credentials
#   creds = None
#   # The file token.json stores the user's access and refresh tokens, and is
#   # created automatically when the authorization flow completes for the first
#   # time.
#   if os.path.exists("token.json"):
#     creds = Credentials.from_authorized_user_file("token.json", SCOPES)
#   # If there are no (valid) credentials available, let the user log in.
#   if not creds or not creds.valid:
#     if creds and creds.expired and creds.refresh_token:
#       creds.refresh(Request())
#     else:
#       flow = InstalledAppFlow.from_client_secrets_file(
#           "credentials.json", SCOPES
#       )
#       creds = flow.run_local_server(port=0)
#     # Save the credentials for the next run
#     with open("token.json", "w") as token:
#       token.write(creds.to_json())

#   return creds


def get_worksheet():
  """
  Get the gspread worksheet object.

  Returns:
    gspread.Worksheet: The worksheet object
  """
  try:
    gc = gspread.service_account(filename=CREDENTIALS_FILE)
    spreadsheet = gc.open_by_key(SPREADSHEET_ID)
    worksheet = spreadsheet.worksheet(WORKSHEET_NAME)
    return worksheet
  except Exception as e:
    print(f"Error accessing Google Sheet: {e}")
    return None


def get_values():
  values = get_sheets_data()
  if not values:
    return [], []

  # Separate rows based on whether column B has data
  rows_with_b_data = []  # List of [A, B] pairs where B has data
  rows_without_b_data = []  # List of A values where B is empty

  for row in values:
    # Ensure we have at least column A
    if len(row) >= 1:
      col_a = row[0].strip() if row[0] else ""

      # Check if column B exists and has data
      if len(row) >= 2 and row[1] and row[1].strip():
        col_b = row[1].strip()
        rows_with_b_data.append([col_a, col_b])
      else:
        # Column B is empty or doesn't exist
        if col_a:  # Only add if column A has data
          rows_without_b_data.append(col_a)

  return rows_with_b_data, rows_without_b_data


def get_active_repeaters():
  """
  Retrieve only active repeaters (rows where column B has data).

  Returns:
    list: List of [prefix, name] pairs for active repeaters
  """
  rows_with_b_data, _ = get_values()
  return rows_with_b_data


def get_unassigned_prefixes():
  """
  Retrieve only unassigned prefixes (rows where column B is empty).

  Returns:
    list: List of prefix strings for unassigned prefixes
  """
  _, rows_without_b_data = get_values()
  return rows_without_b_data


def assign_prefix_name(prefix, name):
  """
  Assign a name to a prefix by updating the Google Sheet.

  Args:
    prefix (str): The prefix to find in column A
    name (str): The name to assign in column B

  Returns:
    bool: True if successful, False if prefix not found or error occurred
  """
  worksheet = get_worksheet()
  if not worksheet:
    return False

  #     values = get_sheets_data()
  # if not values:
  #   return False
  # # Find the row index where the prefix matches (case-insensitive)
  # row_index = None
  # prefix_upper = prefix.strip().upper()
  # for i, row in enumerate(values):
  #   if len(row) >= 1 and row[0].strip().upper() == prefix_upper:
  #     row_index = i
  #     break

  try:
    # Get all values to find the row
    values = worksheet.get_all_values()
    if not values:
      return False

    # Find the row index where the prefix matches (case-insensitive)
    row_index = None
    prefix_upper = prefix.strip().upper()
    for i, row in enumerate(values):
      if len(row) >= 1 and row[0].strip().upper() == prefix_upper:
        row_index = i + 1  # gspread uses 1-based indexing
        break

    if row_index is None:
      print(f"Prefix '{prefix}' not found in the sheet.")
      return False

  #     # Calculate the actual row number in the sheet (accounting for the range start)
  # # Assuming range starts from row 2 (A2:B257), so add 2 to get actual row number
  # range_start_row = int(RANGE_NAME.split('!')[1].split(':')[0][1:])  # Extract starting row number
  # actual_row = range_start_row + row_index

  # # Update the cell in column B
  # cell_range = f"{RANGE_NAME.split('!')[0]}!B{actual_row}"

  # body = {
  #   'values': [[name]]
  # }

  # # Load credentials
  # creds = get_credentials()

  # try:
  #   service = build("sheets", "v4", credentials=creds)
  #   sheet = service.spreadsheets()
  #   result = (
  #       sheet.values()
  #       .update(
  #           spreadsheetId=SPREADSHEET_ID,
  #           range=cell_range,
  #           valueInputOption='RAW',
  #           body=body
  #       )
  #       .execute()
  #   )

  #   # gc = gspread.service_account(filename='creds.json')
  #   # sheet_name = 'Repeaters'
  #   # cell = f'B{actual_row}'

  #   # spreadsheet = gc.open_by_key(SPREADSHEET_ID)
  #   # worksheet = spreadsheet.worksheet(sheet_name)
  #   # color = {'red': 0, 'green': 1, 'blue': 0}

  #   # worksheet.format(cell, {'backgroundColor': color})

    # Update the cell in column B
    worksheet.update_cell(row_index, 2, name)  # Column B = 2

    print(f"Successfully assigned '{name}' to prefix '{prefix}'")
    return True

  except APIError as err:
    print(f"Error updating Google Sheet: {err}")
    return False


def get_sheets_data():
  """
  Retrieve raw data from Google Sheets.

  Returns:
    list: Raw values from the Google Sheet
  """
  worksheet = get_worksheet()
  if not worksheet:
    return []

  try:
    # service = build("sheets", "v4", credentials=creds)

    # # Call the Sheets API
    # sheet = service.spreadsheets()
    # result = (
    #     sheet.values()
    #     .get(spreadsheetId=SPREADSHEET_ID, range=RANGE_NAME)
    #     .execute()
    # )
    # values = result.get("values", [])
    # Get all values from the worksheet
    values = worksheet.get_all_values()

    if not values:
      print("No data found.")
      return []

    return values

  except APIError as err:
    print(f"Error accessing Google Sheets: {err}")
    return []


def get(data_type="both"):
  """
  Get data from Google Sheets based on the specified type.

  Args:
    data_type (str): What data to retrieve
      - "active": Only active repeaters
      - "unassigned": Only unassigned prefixes
      - "both": Both active repeaters and unassigned prefixes (default)
  """
  if data_type == "active":
    active_repeaters = get_active_repeaters()
    print(f"=== Active Repeaters ({len(active_repeaters)}) ===")
    for prefix, name in active_repeaters:
      print(f"{prefix}: {name}")
    print(f"\nTotal Active Repeaters: {len(active_repeaters)}")

  elif data_type == "unassigned":
    unassigned_prefixes = get_unassigned_prefixes()
    print(f"=== Unassigned Prefixes ({len(unassigned_prefixes)}) ===")
    for prefix in unassigned_prefixes:
      print(f"{prefix}")
    print(f"\nTotal Unassigned Prefixes: {len(unassigned_prefixes)}")

  elif data_type == "both":
    # Display both types of data
    active_repeaters = get_active_repeaters()
    print(f"=== Active Repeaters ({len(active_repeaters)}) ===")
    for prefix, name in active_repeaters:
      print(f"{prefix}: {name}")

    unassigned_prefixes = get_unassigned_prefixes()
    print(f"\n=== Unassigned Prefixes ({len(unassigned_prefixes)}) ===")
    for prefix in unassigned_prefixes:
      print(f"{prefix}")

    print("\nSummary:")
    print(f"- Active Repeaters: {len(active_repeaters)}")
    print(f"- Unassigned Prefixes: {len(unassigned_prefixes)}")

  else:
    print(f"Invalid data_type: '{data_type}'. Use 'active', 'unassigned', or 'both'")


def update_coordinates(prefix, coordinates):
  """
  Update coordinates for a repeater in column C.

  Args:
    prefix (str): The prefix to find in column A
    coordinates (str): The coordinates to assign in column C (e.g., "40.7128,-74.0060")

  Returns:
    bool: True if successful, False if prefix not found or error occurred
  """
  worksheet = get_worksheet()
  if not worksheet:
    return False

  try:
    # Get all values to find the row
    values = worksheet.get_all_values()
    if not values:
      return False

    # Find the row index where the prefix matches (case-insensitive)
    row_index = None
    prefix_upper = prefix.strip().upper()
    for i, row in enumerate(values):
      if len(row) >= 1 and row[0].strip().upper() == prefix_upper:
        row_index = i + 1  # gspread uses 1-based indexing
        break

    if row_index is None:
      print(f"Prefix '{prefix}' not found in the sheet.")
      return False

  #       # Calculate the actual row number in the sheet (accounting for the range start)
  # range_start_row = int(RANGE_NAME.split('!')[1].split(':')[0][1:])  # Extract starting row number
  # actual_row = range_start_row + row_index

  # # Update the cell in column C
  # cell_range = f"{RANGE_NAME.split('!')[0]}!C{actual_row}"
  # body = {
  #   'values': [[coordinates]]
  # }

  # # Load credentials
  # creds = get_credentials()

  # try:
  #   service = build("sheets", "v4", credentials=creds)
  #   sheet = service.spreadsheets()
  #   result = (
  #       sheet.values()
  #       .update(
  #           spreadsheetId=SPREADSHEET_ID,
  #           range=cell_range,
  #           valueInputOption='RAW',
  #           body=body
  #       )
  #       .execute()
  #   )

  #   print(f"Successfully updated coordinates '{coordinates}' for prefix '{prefix}' at row {actual_row}")

    # Update the cell in column C
    worksheet.update_cell(row_index, 3, coordinates)  # Column C = 3

    print(f"Successfully updated coordinates '{coordinates}' for prefix '{prefix}'")
    return True

  except APIError as err:
    print(f"Error updating coordinates: {err}")
    return False


def set(prefix, name):
  unassigned_prefixes = get_unassigned_prefixes()
  if not unassigned_prefixes:
    print("No unassigned prefixes found.")
    return

  success = assign_prefix_name(prefix, name)
  if success:
    print(f"Successfully assigned '{name}' to '{prefix}'")
  else:
    print(f"Failed to assign '{name}' to '{prefix}'")

if __name__ == "__main__":
  set("a5", "Test Repeater")