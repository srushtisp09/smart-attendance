FROM python:3.12-slim
WORKDIR /code
COPY requirements.txt .
# insightface depends on the full opencv-python (needs libGL); swap it for the headless build
RUN pip install --no-cache-dir -r requirements.txt \
 && pip uninstall -y opencv-python opencv-python-headless \
 && pip install --no-cache-dir --force-reinstall --no-deps opencv-python-headless==4.11.0.86
# Download the face model into the image now, so the first scan isn't slow and needs no internet
RUN python -c "from insightface.app import FaceAnalysis; FaceAnalysis(name='buffalo_sc', root='/models', providers=['CPUExecutionProvider'], allowed_modules=['detection','recognition'])"
COPY app app 