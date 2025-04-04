import streamlit as st
import google.generativeai as genai
from google.generativeai import types
from google.api_core import exceptions as google_exceptions
import os
import json
from PIL import Image
import io
import re
import requests # Added for making HTTP requests

# --- Default Prompt ---
DEFAULT_PROMPT = """
## **Objective:**
We have an **engineering diagram** that depicts a complex assembly of spare parts. This diagram serves as the **blueprint** for the manufacturer, who will supply the product based on its specifications. Once the product is delivered, our **Quality Assurance (QA) Team** is responsible for verifying its accuracy and ensuring it meets the required standards.

To facilitate this process, we need to **generate a structured QA documentation template** that the QA Team will use for inspection. This document must be created directly from the **engineering diagram** and should accurately capture all relevant details, including component specifications, dimensional data, tolerances, and other verification criteria.

---

## **Instructions:**
1.  **Analyze the Engineering Diagram:**
    - Read the image **block by block** and identify all elements present, including:
        - **Diagrams** (visual representations of parts)
        - **Legends** (explanations of symbols, annotations, and notes)
        - **Footnotes** (additional clarifications or specifications)
        - **Dimension representations** (such as length, width, diameter, radius, surface finish, and Total Indicator Runout (TIR))
    - These details may be **directly mentioned** in the diagram, marked with **symbols and referenced in the legend**, or **noted once but applicable to multiple regions** within the diagram.
    - The system must interpret the diagram like a **human inspector**, recognizing contextual relationships between dimensions, labels, and references.

2.  **Generate Structured JSON Output:**
    - The extracted data should be formatted into a structured **JSON** file. Ensure the output ONLY contains the JSON structure requested below, starting with `{` and ending with `}`. Do not include any introductory text or markdown formatting like ```json.
    - The JSON must have two key sections:

    ```json
    {
        "detailed_raw_data_blocks_of_diagram": [],
        "refined_data": {
            "Header Information": {
                "Part No.": "[Extracted Part Number or N/A]",
                "Part Description": "[Extracted Description or N/A]",
                "Heat No.": "[Extracted Heat Number or N/A]",
                "DWG No. and Rev.": "[Extracted Drawing Number and Revision or N/A]",
                "Serial No.": "[Extracted Serial Number or N/A]",
                "Procedure No. and Rev.": "[Extracted Procedure Number and Revision or N/A]"
            },
            "Dimensions Table": [
                {
                    "Dimension Type": "[Length/Width/Diameter/etc.]",
                    "Dimension Value": "[Extracted Value]",
                    "Dimension Tolerance": "[Extracted Tolerance or N/A]"
                }
            ]
        }
    }
    ```

    - **`detailed_raw_data_blocks_of_diagram`**: This array should list all identified blocks from the diagram in detail, capturing every element and its associated information as observed.
    - **`refined_data`**: This section should be a structured and cleaned version of the extracted data, specifically formatted into the nested "Header Information" and "Dimensions Table" structure as shown above. Populate the fields based on the diagram analysis. If a value is not found, use "N/A". The "Dimensions Table" should be an array of objects, each representing one identified dimension.

---

## **Final QA Document Format (Informational - structure is defined in the JSON):**

### **Header Information**
| Field             | Value                      |
|-------------------|----------------------------|
| **Part No.**      | *[Value from JSON]*        |
| **Part Description**| *[Value from JSON]*        |
| **Heat No.**      | *[Value from JSON]*        |
| **DWG No. and Rev.**| *[Value from JSON]*        |
| **Serial No.**    | *[Value from JSON]*        |
| **Procedure No. and Rev.** | *[Value from JSON]* |

### **Dimensions Table**
| **Dimension Type** | **Dimension Value** | **Dimension Tolerance** |
|--------------------|--------------------|------------------------|
| *[Value from JSON]* | *[Value from JSON]* | *[Value from JSON]*     |
"""

# --- Available Models ---
# Updated list as requested
AVAILABLE_MODELS = [
    "gemini-2.5-pro-exp-03-25" # Keep experimental if you have access
]

# --- External API Endpoint ---
TABLE_CONVERSION_API_URL = "https://vivekaa.in:1300/convert"
# Note: Using verify=False is generally discouraged in production due to security risks.
# If the server has a self-signed certificate, consider adding it to your trust store.
DISABLE_SSL_VERIFICATION = True # Set to False if the server has a valid CA-signed certificate

# --- Streamlit App Configuration ---
st.set_page_config(page_title="Engineering Diagram QA Assistant", layout="wide")
st.title("⚙️ Engineering Diagram QA Assistant")
st.caption("Upload an engineering diagram, get JSON data, and view/download as an HTML table via API.")

# --- Sidebar for Configuration ---
with st.sidebar:
    st.header("Configuration")
    api_key = st.text_input("Enter your Google Gemini API Key:", type="password")

    # Model Selection
    selected_model_name = st.selectbox(
        "Select Gemini Model:",
        options=AVAILABLE_MODELS,
        index=0, # Default to the first model in the list
        help="Choose the Gemini model for analysis. Models differ in capability, speed, and cost."
    )

    st.subheader("Analysis Prompt")
    st.info("Edit the prompt below to customize the analysis instructions for the AI model.")
    prompt = st.text_area("Prompt:", value=DEFAULT_PROMPT, height=350)

    # Check if API key is entered
    if not api_key:
        st.warning("Please enter your Gemini API Key to proceed.")
        st.stop() # Stop execution if no API key

    # Configure GenAI client
    try:
        genai.configure(api_key=api_key)
    except Exception as e:
        st.error(f"Failed to configure Gemini Client: {e}")
        st.stop()

# --- Function to wrap table HTML in a basic HTML document structure ---
def generate_full_html_doc(table_html_content, title="QA Report"):
    """Wraps the provided HTML table content in a basic HTML document structure."""
    return f"""<!DOCTYPE html>
<html>
<head>
    <title>{title}</title>
    <style>
        body {{ font-family: sans-serif; margin: 20px; }}
        table {{ border-collapse: collapse; width: 90%; margin-bottom: 20px; border: 1px solid #ddd; }}
        th, td {{ text-align: left; padding: 8px; border: 1px solid #ddd; }}
        th {{ background-color: #f2f2f2; }}
        tr:nth-child(even) {{ background-color: #f9f9f9; }}
        h1, h2 {{ border-bottom: 1px solid #ccc; padding-bottom: 5px; }}
    </style>
</head>
<body>
    <h1>{title}</h1>
    {table_html_content}
</body>
</html>"""

# --- Main Area ---
st.header("Diagram Upload & Analysis")
uploaded_file = st.file_uploader("Choose an engineering diagram image...", type=["png", "jpg", "jpeg"])

# Initialize session state
if 'gemini_analysis_data' not in st.session_state:
    st.session_state.gemini_analysis_data = None
if 'gemini_error' not in st.session_state:
    st.session_state.gemini_error = None
if 'table_html_content' not in st.session_state:
    st.session_state.table_html_content = None
if 'table_api_error' not in st.session_state:
    st.session_state.table_api_error = None
if 'raw_text_on_json_error' not in st.session_state:
     st.session_state.raw_text_on_json_error = None

if uploaded_file is not None:
    st.image(uploaded_file, caption="Uploaded Diagram", use_column_width=True)

    if st.button("Analyze Diagram & Generate Table"):
        # Clear previous results
        st.session_state.gemini_analysis_data = None
        st.session_state.gemini_error = None
        st.session_state.table_html_content = None
        st.session_state.table_api_error = None
        st.session_state.raw_text_on_json_error = None
        refined_data_for_table = None # Reset local variable

        # 1. --- Call Gemini API ---
        try:
            img = Image.open(uploaded_file)
            st.info(f"Contacting Gemini model: {selected_model_name}...")
            model = genai.GenerativeModel(selected_model_name)
            contents = [prompt, img]

            with st.spinner(f"Analyzing diagram with {selected_model_name}..."):
                response = model.generate_content(contents)

            raw_text = response.text

            # 2. --- Parse Gemini JSON Response ---
            try:
                match = re.search(r'```json\s*(\{.*?\})\s*```', raw_text, re.DOTALL | re.IGNORECASE)
                if match:
                    json_string = match.group(1)
                else:
                    json_start_index = raw_text.find('{')
                    if json_start_index != -1:
                         json_end_index = raw_text.rfind('}')
                         if json_end_index > json_start_index:
                              json_string = raw_text[json_start_index:json_end_index+1]
                         else: # Fallback if closing brace isn't found properly
                             json_string = raw_text
                    else: # Fallback if no '{' found
                        json_string = raw_text

                st.session_state.gemini_analysis_data = json.loads(json_string)

                # Extract refined_data for the table API call
                if "refined_data" in st.session_state.gemini_analysis_data and \
                   isinstance(st.session_state.gemini_analysis_data["refined_data"], dict):
                   refined_data_for_table = st.session_state.gemini_analysis_data["refined_data"]
                else:
                    st.session_state.gemini_error = "Gemini response parsed, but 'refined_data' key is missing or not a dictionary."
                    # Don't proceed to table API if refined_data isn't found

            except json.JSONDecodeError:
                st.session_state.gemini_error = "Failed to decode the Gemini response as JSON."
                st.session_state.raw_text_on_json_error = raw_text # Store raw text for debugging
            except Exception as e:
                 st.session_state.gemini_error = f"An error occurred parsing the Gemini JSON response: {e}"
                 st.session_state.raw_text_on_json_error = raw_text

        # --- Catch Gemini API Errors ---
        except google_exceptions.PermissionDenied as e:
             st.session_state.gemini_error = f"Gemini Auth Error: Check API Key. Details: {e}"
        except google_exceptions.ResourceExhausted as e:
             st.session_state.gemini_error = f"Gemini Quota Exceeded. Details: {e}"
        except (genai.types.BlockedPromptException, genai.types.StopCandidateException) as e:
             st.session_state.gemini_error = f"Gemini Content Generation Error: {e}"
        except AttributeError:
             st.session_state.gemini_error = "Could not access Gemini response data. API call might have failed."
        except Exception as e:
            st.session_state.gemini_error = f"An unexpected error occurred during Gemini analysis: {e}"


        # 3. --- Call Table Conversion API (only if Gemini call succeeded and refined_data exists) ---
        if st.session_state.gemini_analysis_data and not st.session_state.gemini_error and refined_data_for_table:
            st.info("Sending data to Table Conversion API...")
            headers = {'Content-Type': 'application/json'}
            try:
                # Use verify=False cautiously
                api_response = requests.post(
                    TABLE_CONVERSION_API_URL,
                    headers=headers,
                    data=json.dumps(refined_data_for_table), # Send the refined_data part
                    timeout=30, # Add a timeout
                    verify=not DISABLE_SSL_VERIFICATION # Use flag to control verification
                )
                api_response.raise_for_status() # Raises HTTPError for bad responses (4xx or 5xx)

                st.session_state.table_html_content = api_response.text
                st.success("Analysis and Table Generation Complete!")

            except requests.exceptions.Timeout:
                st.session_state.table_api_error = "Table Conversion API request timed out."
            except requests.exceptions.ConnectionError:
                st.session_state.table_api_error = f"Could not connect to the Table Conversion API at {TABLE_CONVERSION_API_URL}. Check if the server is running and accessible."
            except requests.exceptions.SSLError as e:
                 st.session_state.table_api_error = f"SSL Error connecting to Table API: {e}. " + \
                      ("Consider setting DISABLE_SSL_VERIFICATION to True if using a self-signed certificate (use with caution)." if not DISABLE_SSL_VERIFICATION else "")
            except requests.exceptions.HTTPError as e:
                 st.session_state.table_api_error = f"Table Conversion API returned an error: {e.response.status_code} {e.response.reason}. Response: {e.response.text[:200]}..." # Show beginning of error response
            except requests.exceptions.RequestException as e:
                st.session_state.table_api_error = f"An error occurred calling the Table Conversion API: {e}"
            except Exception as e:
                 st.session_state.table_api_error = f"An unexpected error occurred during table conversion: {e}"


# --- Display Results Area ---
st.divider()
st.subheader("Analysis Results")

# Display Gemini Errors first if they occurred
if st.session_state.gemini_error:
    st.error(f"Gemini Analysis Error: {st.session_state.gemini_error}")
    if st.session_state.raw_text_on_json_error:
        with st.expander("View Raw Text from Gemini (on JSON parse error)"):
            st.text(st.session_state.raw_text_on_json_error)

# Display Table API Errors if they occurred
if st.session_state.table_api_error:
     st.error(f"Table Conversion Error: {st.session_state.table_api_error}")

# Display Tabs if Gemini analysis data is available
if st.session_state.gemini_analysis_data:
    tab1, tab2 = st.tabs(["Raw JSON Output", "Refined QA Data Table (from API)"])

    with tab1:
        st.json(st.session_state.gemini_analysis_data)

    with tab2:
        if st.session_state.table_html_content:
            st.markdown("#### Table Generated via API:")
            st.markdown(st.session_state.table_html_content, unsafe_allow_html=True)

            # Offer download only if table HTML is available
            try:
                # Wrap the API HTML in a full document for better download compatibility
                full_html_doc = generate_full_html_doc(st.session_state.table_html_content, title="QA Report")
                st.download_button(
                    label="⬇️ Download QA Data as HTML",
                    data=full_html_doc,
                    file_name="qa_report.html",
                    mime="text/html",
                    key="html_download" # Added key for stability
                )
            except Exception as e:
                 st.error(f"Error preparing HTML for download: {e}")

        elif not st.session_state.table_api_error:
             # Condition where Gemini data exists but table API wasn't called or finished yet
             st.info("Table data will appear here after successful API conversion.")
        # Error message for table API is handled above the tabs

elif not st.session_state.gemini_error and uploaded_file is None:
    st.info("Upload an image file and click 'Analyze Diagram & Generate Table' to begin.")
elif not st.session_state.gemini_error and not st.session_state.gemini_analysis_data:
     # This state occurs if analysis hasn't been run yet after upload
     st.info("Click the 'Analyze Diagram & Generate Table' button to process the uploaded image.")