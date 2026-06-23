llama-server \
  -m GLM-4.7-Flash-Q6_K.gguf \
  --alias glm-4.7-flash \
  --port 8082 \
  --jinja \
  -ngl 99 \
  -np 1 \
  -c 163840 \
  -ctk q8_0 -ctv q8_0 \
  --host 127.0.0.1
