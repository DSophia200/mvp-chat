가상공간생성
conda create -n 이름 python=3.12
conda acivate 이름


필요한 Python 패키지를 설치합니다. 

pip install -r requirements.txt

pip install boto3


도커
docker build -t 사용자지정이름 .
docker run -p 8501:8501 사용자지정이름

pip install -U langchain-aws

pip install PyMuPDF

pip install pytesseract

pip install -U langchain-unstructured
