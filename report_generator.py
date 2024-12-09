import pandas as pd
import json
from jinja2 import Environment, FileSystemLoader
import pdfkit
from datetime import datetime
import re

# Set up Jinja2 environment
env = Environment(loader=FileSystemLoader('templates'))

# pdfkit setup
pdfkit_config = pdfkit.configuration(wkhtmltopdf="C:/Program Files/wkhtmltopdf/bin/wkhtmltopdf.exe")

# Define the CSV file path
csv_file_path = "dummy_data.csv"

# Load the CSV data into a pandas DataFrame
df = pd.read_csv(csv_file_path, header=[0, 1, 2])

new_columns = []
for col in df.columns.to_frame().values:
    fixed_col = list(col)  # Copy the original column
    # Replace "Unnamed" headers with the last valid header
    if str(col[0]).startswith("Unnamed"):
        fixed_col[0] = new_columns[-1][0] if new_columns else col[0]
    new_columns.append(tuple(fixed_col))

# Update the DataFrame's columns with the fixed MultiIndex
df.columns = pd.MultiIndex.from_tuples(new_columns)

def calculate_age(dob):
    today = datetime.today()
    dob_date = datetime.strptime(dob, "%d-%m-%Y") 
    age = today.year - dob_date.year - ((today.month, today.day) < (dob_date.month, dob_date.day))
    return age

# Function to transform a single row into the required data structure
def transform_row_to_patient_data(row):
    """
    Transform a single row into the required hierarchical data structure,
    with 'age' calculated and added under the same subheader as 'date_of_birth'.
    Remove self-referential column names if they start with the header name.
    """
    # Convert the row to a dictionary for reliable MultiIndex access
    row_dict = row.to_dict()
    
    patient_data = {}
    for header in df.columns.get_level_values(0).unique():
        # Normalize the header for consistent comparison
        header_normalized = header.lower()

        # Filter columns for this header
        header_columns = df.loc[:, df.columns.get_level_values(0) == header]

        grouped_by_subheader = {}
        for subheader in header_columns.columns.get_level_values(1).unique():
            # Filter columns for this subheader
            subheader_columns = header_columns.loc[
                :, header_columns.columns.get_level_values(1) == subheader
            ]

            # Use the dictionary to access values reliably
            subheader_data = {}
            for col in subheader_columns.columns.get_level_values(2):
                value = row_dict.get((header, subheader, col))
                if pd.notna(value):
                    # Normalize the column name for consistent comparison
                    col_normalized = col.lower()

                    # Remove self-referential prefix if present
                    if col_normalized.startswith(f"{header_normalized}_"):
                        clean_col = col[len(header) + 1:]  # Remove the header prefix and the underscore
                    else:
                        clean_col = col

                    subheader_data[clean_col] = value

            # If 'date_of_birth' exists, calculate 'age' and add it
            if "date_of_birth" in subheader_data:
                dob = subheader_data["date_of_birth"]
                try:
                    subheader_data["age"] = calculate_age(dob)
                except ValueError:
                    # Handle invalid date format or missing date
                    subheader_data["age"] = "Invalid DOB"

            grouped_by_subheader[subheader] = subheader_data

        # Add the grouped subheaders under the main header
        patient_data[header] = grouped_by_subheader

    return patient_data


# Apply transformation to each row in the DataFrame
all_patient_data = [transform_row_to_patient_data(row) for _, row in df.iterrows()]

# Save the processed data to a JSON file for debugging or further processing
output_json_path = "output/all_patient_data.json"
with open(output_json_path, "w", encoding="utf-8") as json_file:
    json.dump(all_patient_data, json_file, indent=4)

# Debugging: Confirm data processing
print(f"Processed data for {len(all_patient_data)} patients saved to {output_json_path}")

# Loop through all patients to generate PDFs
for patient_data in all_patient_data:
    medical_record_number = None

    # Access 'MASTER DATA' and loop through its subheaders
    for subheader, fields in patient_data['MASTER DATA'].items():
        # Check if 'medical_record_number' exists in the current subheader
        if 'medical_record_number' in fields:
            medical_record_number = fields['medical_record_number']
            break  # Exit loop once found

    # Sanitize the medical record number
    if medical_record_number:
        safe_medical_record_number = re.sub(r'[^\w\-_]', '_', medical_record_number)
    else:
        raise KeyError("medical_record_number not found in MASTER DATA")

    # Prep cover page render
    cover_page_html = env.get_template('cover_page.html').render(data=patient_data)
    # Prep executive summary render
    executive_summary_html = env.get_template('executive_summary.html').render(data=patient_data)
    # Prep auto page renders
    sections = {
        key.replace("_", " ").title(): {
            (
                nested_key[len(key) + 1:].replace("_", " ").title()
                if nested_key.lower().startswith(key.lower() + "_")
                else nested_key.replace("_", " ").title()
            ): nested_value
            for nested_key, nested_value in value.items() if nested_value  # Only include non-empty values
        }
        for key, value in patient_data.items()
        if key != "MASTER DATA" and value  # Exclude MASTER DATA and empty sections
    }
    # Filter out headers with no subheaders
    sections = {header: subheaders for header, subheaders in sections.items() if subheaders}

    examination_html = env.get_template('examination_pages.html').render(data=patient_data, sections=sections)

    # Combine HTMLs
    combined_html = f"{cover_page_html}\n<div style='page-break-before: always'></div>\n{executive_summary_html}\n<div style='page-break-before: always'></div>{examination_html}"
    output_pdf_path = f"output/{safe_medical_record_number}_mcu_report.pdf"

    # # Save the combined HTML to a file for manual debugging
    # debug_html_path = f"output/{safe_medical_record_number}_mcu_report.html"
    # with open(debug_html_path, "w", encoding="utf-8") as f:
    #     f.write(combined_html)

    # Generate the PDF
    pdfkit.from_string(
        combined_html,
        output_pdf_path,
        options={
            'enable-local-file-access': True,  # Allow access to local files
            'quiet': '',  # Suppress logs from wkhtmltopdf
            'page-size': 'A4',
        },
        configuration=pdfkit_config
    )

    print(f"Generated PDF for patient {medical_record_number}")

print("All PDFs generated successfully!")


