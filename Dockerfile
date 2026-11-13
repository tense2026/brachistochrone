# Reproduces the variable study headlessly and bit-for-bit.
FROM python:3.13-slim

# Matplotlib needs a writable cache dir and a non-interactive backend; the
# container has no display, so Agg is the only backend that can work here.
ENV MPLBACKEND=Agg \
    MPLCONFIGDIR=/tmp/mpl \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /app

# Dependencies first so code edits do not invalidate the pip layer.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY *.py ./
COPY *.md ./

# Fail the build if the physics regressions do not hold.
RUN python -m unittest -q test_project test_magnus

# Writable output dir for a non-root run.
RUN mkdir -p /app/out && chmod 777 /app/out /tmp
USER 1000:1000

# Default: re-run the exact published configuration into a mounted volume.
ENTRYPOINT ["python"]
CMD ["variable_study.py", "--episodes", "180", "--pop-size", "20", \
     "--height", "5", "--length", "10", "--no-show", "--output-dir", "/app/out"]
