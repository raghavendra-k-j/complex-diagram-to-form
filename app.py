# --- Imports ---
import streamlit as st
import google.generativeai as genai
from google.generativeai import types
from google.api_core import exceptions as google_exceptions
import os
import json
from PIL import Image
import io
import re
import requests # For external API call
# Removed: from json2table import convert as local_convert

# --- Default Prompt ---
# (Keep the DEFAULT_PROMPT as it is)
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

    - **`detailed_raw_data_blocks_of_diagram`**: This array should list all identified blocks from the diagram in detail, capturing every element and its associated information as observed. The structure of objects within this array might vary based on the detected block.
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
AVAILABLE_MODELS = [
    "gemini-2.5-pro-exp-03-25",
]

# --- External API Endpoint ---
TABLE_CONVERSION_API_URL = "https://vivekaa.in:1300/convert"
DISABLE_SSL_VERIFICATION = True # Use with caution

# --- Table Styling ---
# Consistent styling for downloads generated via API
TABLE_STYLES = """
<style>
    body { font-family: sans-serif; margin: 20px; }
    table { border-collapse: collapse; width: 95%; margin-bottom: 20px; border: 1px solid #ddd; }
    th, td { text-align: left; padding: 8px; border: 1px solid #ddd; word-wrap: break-word; } /* Added word-wrap */
    th { background-color: #f2f2f2; font-weight: bold;}
    tr:nth-child(even) { background-color: #f9f9f9; }
    h1, h2 { border-bottom: 1px solid #ccc; padding-bottom: 5px; margin-top: 30px;}
</style>
"""
# Removed: LOCAL_TABLE_ATTRIBUTES_DISPLAY and LOCAL_TABLE_ATTRIBUTES_DOWNLOAD


# --- Streamlit App Configuration ---
st.set_page_config(page_title="Engineering Diagram QA Assistant", layout="wide")
st.title("⚙️ Engineering Diagram QA Assistant")
st.caption("Upload diagram -> Get JSON -> View API-Generated Raw/Refined Tables -> Download")

# --- Sidebar ---
with st.sidebar:
    st.header("Configuration")
    # Retrieve API key from environment variable (recommended) or text input
    default_api_key = "AIzaSyAkbWOdvXvddYhK05cKLXPhiGWvqCt4t6U"
    api_key = st.text_input(
        "Enter Google Gemini API Key:",
        type="password",
        value=default_api_key,
        help="It's recommended to set the GOOGLE_API_KEY environment variable."
    )

    selected_model_name = st.selectbox(
        "Select Gemini Model:", options=AVAILABLE_MODELS, index=0,
        help="Choose the Gemini model for analysis."
    )
    st.subheader("Analysis Prompt")
    st.info("Edit the prompt for the AI model.")
    prompt = st.text_area("Prompt:", value=DEFAULT_PROMPT, height=350)

    if not api_key:
        st.warning("Please enter your Google Gemini API Key.")
        st.stop()
    try:
        genai.configure(api_key=api_key)
    except Exception as e:
        st.error(f"Gemini Client Config Error: {e}")
        st.stop()

# --- Function to wrap table HTML in a full document ---
def generate_full_html_doc(table_html_content, title="QA Report"):
    # Check if the content already looks like a full HTML document
    if table_html_content and table_html_content.strip().lower().startswith('<!doctype html'):
        return table_html_content # Assume API returned full doc
    # Otherwise, wrap it
    return f"""<!DOCTYPE html>
<html><head><title>{title}</title>{TABLE_STYLES}</head>
<body><h1>{title}</h1>{table_html_content}</body></html>"""

# --- Main Area ---
st.header("Diagram Upload & Analysis")
uploaded_file = st.file_uploader("Choose diagram image...", type=["png", "jpg", "jpeg"])

# --- Initialize Session State ---
if 'gemini_analysis_data' not in st.session_state: st.session_state.gemini_analysis_data = None
if 'gemini_error' not in st.session_state: st.session_state.gemini_error = None
if 'raw_text_on_json_error' not in st.session_state: st.session_state.raw_text_on_json_error = None
# Raw Table (API Generated)
if 'raw_table_html_content' not in st.session_state: st.session_state.raw_table_html_content = None
if 'raw_table_api_error' not in st.session_state: st.session_state.raw_table_api_error = None
# Refined Table (API Generated)
if 'refined_table_html_content' not in st.session_state: st.session_state.refined_table_html_content = None
if 'refined_table_api_error' not in st.session_state: st.session_state.refined_table_api_error = None

if uploaded_file is not None:
    st.image(uploaded_file, caption="Uploaded Diagram", use_column_width=True)

    if st.button("Analyze Diagram & Generate Tables via API"):
        # --- Reset State ---
        st.session_state.gemini_analysis_data = None
        st.session_state.gemini_error = None
        st.session_state.raw_text_on_json_error = None
        st.session_state.raw_table_html_content = None # Reset raw API content
        st.session_state.raw_table_api_error = None   # Reset raw API error
        st.session_state.refined_table_html_content = None
        st.session_state.refined_table_api_error = None
        raw_data_for_api = None # Renamed for clarity
        refined_data_for_api = None

        # --- 1. Call Gemini API ---
        try:
            img = Image.open(uploaded_file)
            st.info(f"Contacting Gemini model: {selected_model_name}...")
            model = genai.GenerativeModel(selected_model_name)
            contents = [prompt, img]
            with st.spinner(f"Analyzing diagram with {selected_model_name}..."):
                response = model.generate_content(contents)
            raw_text = response.text

            # --- 2. Parse Gemini JSON Response ---
            try:
                # Attempt to find JSON within ```json ``` blocks first
                match = re.search(r'```json\s*(\{.*?\})\s*```', raw_text, re.DOTALL | re.IGNORECASE)
                if match:
                    json_string = match.group(1)
                else:
                    # Fallback: Find the first '{' and the last '}'
                    json_start_index = raw_text.find('{')
                    if json_start_index != -1:
                         json_end_index = raw_text.rfind('}')
                         if json_end_index > json_start_index:
                             json_string = raw_text[json_start_index:json_end_index+1]
                         else:
                             st.session_state.gemini_error = "Could not find valid JSON structure (matching braces)."
                             st.session_state.raw_text_on_json_error = raw_text
                             json_string = None # Ensure no further processing
                    else:
                         st.session_state.gemini_error = "Could not find JSON starting brace '{'."
                         st.session_state.raw_text_on_json_error = raw_text
                         json_string = None # Ensure no further processing

                if json_string: # Proceed only if JSON string was found
                    st.session_state.gemini_analysis_data = json.loads(json_string)

                    # Extract data for tables (check existence and type)
                    if "detailed_raw_data_blocks_of_diagram" in st.session_state.gemini_analysis_data and \
                       isinstance(st.session_state.gemini_analysis_data["detailed_raw_data_blocks_of_diagram"], list):
                       raw_data_for_api = st.session_state.gemini_analysis_data["detailed_raw_data_blocks_of_diagram"]
                    else:
                        # Set error state for the specific table API call later if needed
                        st.warning("Key 'detailed_raw_data_blocks_of_diagram' missing or not a list in Gemini JSON. Raw table cannot be generated.")


                    if "refined_data" in st.session_state.gemini_analysis_data and \
                       isinstance(st.session_state.gemini_analysis_data["refined_data"], dict):
                       refined_data_for_api = st.session_state.gemini_analysis_data["refined_data"]
                    else:
                       # Set error state for the specific table API call later if needed
                       st.warning("Key 'refined_data' missing or not a dictionary in Gemini JSON. Refined table cannot be generated.")

            except json.JSONDecodeError as e:
                st.session_state.gemini_error = f"Failed to decode the Gemini response as JSON: {e}"
                st.session_state.raw_text_on_json_error = raw_text # Store raw text
            except Exception as e:
                 st.session_state.gemini_error = f"Error parsing Gemini JSON: {e}"
                 st.session_state.raw_text_on_json_error = raw_text # Store raw text

        # --- Catch Gemini API Errors ---
        except google_exceptions.PermissionDenied as e: st.session_state.gemini_error = f"Gemini Auth Error: Check API Key. Details: {e}"
        except google_exceptions.ResourceExhausted as e: st.session_state.gemini_error = f"Gemini Quota Exceeded. Details: {e}"
        except (types.BlockedPromptException, types.StopCandidateException) as e: st.session_state.gemini_error = f"Gemini Content Error: Prompt or response blocked. Details: {e}"
        except AttributeError: st.session_state.gemini_error = "Could not access Gemini response data (AttributeError)."
        except Exception as e: st.session_state.gemini_error = f"Unexpected Gemini analysis error: {type(e).__name__} - {e}"


        # --- 3. Call Raw Table Conversion API (if data exists) ---
        if raw_data_for_api is not None: # Check if data was successfully extracted
            st.info("Sending data to Raw Table Conversion API...")
            headers = {'Content-Type': 'application/json'}
            try:
                # Ensure raw_data_for_api is not empty before sending
                if not raw_data_for_api:
                    st.session_state.raw_table_api_error = "The 'detailed_raw_data_blocks_of_diagram' list is empty. Cannot generate raw table."
                else:
                    api_response = requests.post(
                        TABLE_CONVERSION_API_URL, headers=headers,
                        data=json.dumps(raw_data_for_api), timeout=45, # Increased timeout slightly
                        verify=not DISABLE_SSL_VERIFICATION
                    )
                    api_response.raise_for_status() # Raise HTTPError for bad responses (4xx or 5xx)
                    st.session_state.raw_table_html_content = api_response.text # Store raw HTML from API

            except requests.exceptions.Timeout: st.session_state.raw_table_api_error = "Raw Table API request timed out."
            except requests.exceptions.ConnectionError: st.session_state.raw_table_api_error = f"Could not connect to Raw Table API at {TABLE_CONVERSION_API_URL}."
            except requests.exceptions.SSLError as e: st.session_state.raw_table_api_error = f"SSL Error connecting to Raw Table API: {e}." + (" Try setting DISABLE_SSL_VERIFICATION=True for self-signed certs." if not DISABLE_SSL_VERIFICATION else "")
            except requests.exceptions.HTTPError as e: st.session_state.raw_table_api_error = f"Raw Table API Error: {e.response.status_code} {e.response.reason}. Response: {e.response.text[:200]}..."
            except requests.exceptions.RequestException as e: st.session_state.raw_table_api_error = f"Error calling Raw Table API: {e}"
            except Exception as e: st.session_state.raw_table_api_error = f"Unexpected error during Raw Table API call: {type(e).__name__} - {e}"
        elif not st.session_state.gemini_error: # Only show this specific error if Gemini part was okay
             st.session_state.raw_table_api_error = "Raw data structure was missing or invalid in Gemini response. Cannot call Raw Table API."


        # --- 4. Call Refined Table Conversion API (if data exists) ---
        if refined_data_for_api is not None: # Check if data was successfully extracted
            st.info("Sending data to Refined Table Conversion API...")
            headers = {'Content-Type': 'application/json'}
            try:
                # Ensure refined_data_for_api is not empty if it's expected to have content
                if not refined_data_for_api:
                     st.session_state.refined_table_api_error = "The 'refined_data' dictionary is empty. Cannot generate refined table."
                else:
                    api_response = requests.post(
                        TABLE_CONVERSION_API_URL, headers=headers,
                        data=json.dumps(refined_data_for_api), timeout=45, # Increased timeout slightly
                        verify=not DISABLE_SSL_VERIFICATION
                    )
                    api_response.raise_for_status() # Raise HTTPError for bad responses (4xx or 5xx)
                    st.session_state.refined_table_html_content = api_response.text # Store raw HTML from API

            except requests.exceptions.Timeout: st.session_state.refined_table_api_error = "Refined Table API request timed out."
            except requests.exceptions.ConnectionError: st.session_state.refined_table_api_error = f"Could not connect to Refined Table API at {TABLE_CONVERSION_API_URL}."
            except requests.exceptions.SSLError as e: st.session_state.refined_table_api_error = f"SSL Error connecting to Refined Table API: {e}." + (" Try setting DISABLE_SSL_VERIFICATION=True for self-signed certs." if not DISABLE_SSL_VERIFICATION else "")
            except requests.exceptions.HTTPError as e: st.session_state.refined_table_api_error = f"Refined Table API Error: {e.response.status_code} {e.response.reason}. Response: {e.response.text[:200]}..."
            except requests.exceptions.RequestException as e: st.session_state.refined_table_api_error = f"Error calling Refined Table API: {e}"
            except Exception as e: st.session_state.refined_table_api_error = f"Unexpected error during Refined Table API call: {type(e).__name__} - {e}"
        elif not st.session_state.gemini_error: # Only show this specific error if Gemini part was okay
             st.session_state.refined_table_api_error = "Refined data structure was missing or invalid in Gemini response. Cannot call Refined Table API."


        # --- Final Status Update ---
        if not st.session_state.gemini_error and not st.session_state.raw_table_api_error and not st.session_state.refined_table_api_error:
            st.success("Analysis and Table Generation via API Complete!")
        else:
            st.warning("Completed with some errors. Check results below.")


# --- Display Results Area ---
st.divider()
st.subheader("Analysis Results")

# --- Display General Errors First ---
if st.session_state.gemini_error:
    st.error(f"Gemini Analysis Error: {st.session_state.gemini_error}")
    if st.session_state.raw_text_on_json_error:
        with st.expander("View Raw Text from Gemini (on JSON parse error)"): st.text(st.session_state.raw_text_on_json_error)

if st.session_state.raw_table_api_error: # Error during raw table API call
     st.error(f"Raw Table API Error: {st.session_state.raw_table_api_error}")

if st.session_state.refined_table_api_error: # Error during refined table API call
     st.error(f"Refined Table API Error: {st.session_state.refined_table_api_error}")


# --- Display Tabs if Gemini data exists ---
if st.session_state.gemini_analysis_data:
    tab1, tab2, tab3 = st.tabs(["JSON Output", "Raw Data Table (API)", "Refined Data Table (API)"])

    # --- Tab 1: JSON ---
    with tab1:
        st.json(st.session_state.gemini_analysis_data)

    # --- Tab 2: Raw Table (API Generated) ---
    with tab2:
        if st.session_state.raw_table_html_content:
            st.markdown("#### Raw Data Blocks (Generated via API)")
            # Display the HTML content received from the API
            st.markdown(st.session_state.raw_table_html_content, unsafe_allow_html=True)

            # Download button for Raw Table
            try:
                # Wrap the API HTML in a full document structure for download
                full_html_doc_raw = generate_full_html_doc(st.session_state.raw_table_html_content, title="Raw Extracted Data")
                st.download_button(
                    label="⬇️ Download Raw Data as HTML",
                    data=full_html_doc_raw,
                    file_name="raw_data_report.html",
                    mime="text/html",
                    key="raw_api_html_download" # Changed key
                )
            except Exception as e:
                st.error(f"Error preparing Raw API HTML for download: {e}")

        elif not st.session_state.raw_table_api_error:
            st.info("Raw table data will appear here after successful API conversion.")
        # Error message is displayed above tabs if st.session_state.raw_table_api_error is set

    # --- Tab 3: Refined Table (from API) ---
    with tab3:
        if st.session_state.refined_table_html_content:
            st.markdown("#### Refined QA Data (Generated via API)")
            st.markdown(st.session_state.refined_table_html_content, unsafe_allow_html=True)

            # Download button for Refined Table
            try:
                # Wrap the API HTML in a full document structure for download
                full_html_doc_refined = generate_full_html_doc(st.session_state.refined_table_html_content, title="Refined QA Report")
                st.download_button(
                    label="⬇️ Download Refined QA Data as HTML",
                    data=full_html_doc_refined,
                    file_name="refined_qa_report.html",
                    mime="text/html",
                    key="refined_api_html_download" # Changed key slightly for consistency
                )
            except Exception as e:
                 st.error(f"Error preparing Refined API HTML for download: {e}")

        elif not st.session_state.refined_table_api_error:
             st.info("Refined table data will appear here after successful API conversion.")
        # Error message is displayed above tabs if st.session_state.refined_table_api_error is set

# --- Initial state messages ---
elif not st.session_state.gemini_error and uploaded_file is None:
    st.info("Upload an image file and click 'Analyze Diagram & Generate Tables via API' to begin.")
elif not st.session_state.gemini_error and not st.session_state.gemini_analysis_data:
     st.info("Click the 'Analyze Diagram & Generate Tables via API' button to process the uploaded image.")
     



