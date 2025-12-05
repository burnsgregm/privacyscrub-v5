import streamlit as st
import requests
import time

# --- INFRASTRUCTURE CONFIGURATION (Updated) ---
# FIX: Pointing to the active V5 Gateway Service
API_URL = "https://privacyscrub-gateway-138163390354.us-central1.run.app"
API_KEY = "secret" # Placeholder for future auth
# -----------------------------------------------------

st.set_page_config("PrivacyScrub Console", layout="wide")
st.title("PrivacyScrub Enterprise Console V5")

# Sidebar - Privacy Controls
st.sidebar.header("Privacy Controls")
profile = st.sidebar.selectbox("Compliance Profile", ["NONE", "GDPR", "CCPA", "HIPAA_SAFE_HARBOR"])
mode = st.sidebar.radio("Redaction Mode", ["blur", "pixelate", "black_box"])

# Sidebar - Granular Targets
st.sidebar.subheader("Targets (Profile Override)")
t_faces = st.sidebar.checkbox("Faces", True)
t_plates = st.sidebar.checkbox("Plates", True)
t_logos = st.sidebar.checkbox("Logos", False)
t_text = st.sidebar.checkbox("Text (OCR)", False)

headers = {"X-API-KEY": API_KEY}
tab1, tab2 = st.tabs(["Single Image", "Video Job"])

with tab1:
    st.subheader("Image Anonymization")
    img = st.file_uploader("Upload Image", type=['jpg', 'png', 'jpeg'])
    if img and st.button("Process Image"):
        with st.spinner("Redacting PII via GPU Worker..."):
            files = {"file": img.getvalue()}
            # Data must be sent as string representations for Multipart form data
            data = {
                "profile": profile, 
                "mode": mode,
                "target_logos": str(t_logos).lower(), # Convert bool to string for consistency
                "target_text": str(t_text).lower()
            }
            try:
                # Gateway forwards this to the GPU Worker
                r = requests.post(f"{API_URL}/v1/anonymize-image", headers=headers, files=files, data=data)
                
                if r.status_code == 200:
                    c1, c2 = st.columns(2)
                    c1.image(img, caption="Original")
                    c2.image(r.content, caption="Anonymized")
                else:
                    st.error(f"API Error ({r.status_code}): {r.text}")
            except Exception as e:
                st.error(f"Connection Error: {e}")

with tab2:
    st.subheader("Batch Video Processing")
    vid = st.file_uploader("Upload Video", type=['mp4'])
    if vid and st.button("Start Processing Job"):
        with st.spinner("Uploading to Cloud Storage & Queuing Job..."):
            try:
                files = {"file": vid.getvalue()}
                data = {"webhook_url": ""} 
                
                # Gateway uploads to GCS -> Firestore -> Cloud Tasks
                r = requests.post(f"{API_URL}/v1/video", headers=headers, files=files, data=data)
                
                if r.status_code == 200:
                    job_id = r.json()["job_id"]
                    st.success(f"Job Started: {job_id}")
                    
                    status_ph = st.empty()
                    bar = st.progress(0)
                    
                    # Polling Loop
                    while True:
                        time.sleep(3)
                        try:
                            stat = requests.get(f"{API_URL}/v1/jobs/{job_id}", headers=headers).json()
                            s = stat.get('status', 'UNKNOWN')
                            
                            chunks_total = stat.get('chunks_total', 0)
                            chunks_completed = stat.get('chunks_completed', 0)
                            
                            if chunks_total > 0:
                                p = chunks_completed / chunks_total
                            else:
                                p = 0.0
                                
                            status_ph.info(f"Status: {s} | Chunks: {chunks_completed}/{chunks_total}")
                            bar.progress(min(p, 1.0))
                            
                            if s == "COMPLETED":
                                st.success("Processing Complete!")
                                output_url = stat.get('output_url', '#')
                                st.markdown(f"### [Download Result]({output_url})")
                                break
                                
                            if s in ["FAILED", "CANCELLED"]:
                                st.error(f"Job Failed: {stat.get('error_message', 'Unknown error')}")
                                break
                        except Exception as e:
                             st.warning(f"Polling warning: {e}")
                else:
                    st.error(f"API Error: {r.status_code} - {r.text}")
            except Exception as e:
                st.error(f"Connection Error: {e}")
