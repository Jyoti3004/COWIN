FROM python:3.12-slim
WORKDIR /srv
COPY app.py .
ENV PORT=8080 ZONE=unknown
EXPOSE 8080
HEALTHCHECK --interval=10s --timeout=3s CMD python -c "import urllib.request,os;urllib.request.urlopen('http://localhost:'+os.environ.get('PORT','8080')+'/health')" || exit 1
CMD ["python", "app.py"]
