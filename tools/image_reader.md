---
name: image_reader
description: Read and analyze images on disk. Returns metadata and file path; the system auto-injects the image as multimodal content for the model to see.
parameters:
  path:
    type: string
    description: "Absolute or relative path to the image file."
  action:
    type: string
    description: "read (returns metadata + image for visual analysis) or info (metadata only). Default: read."
examples:
  - "Read and describe a screenshot"
  - "What's in this image? Use image_reader on C:/photos/cat.png"
  - "Analyze the diagram at ./assets/architecture.png"
usage_notes:
  - "Supported formats: PNG, JPG/JPEG, GIF, BMP, WebP, TIFF"
  - "action=read returns metadata plus the image path — the system automatically injects the image as multimodal content so the model can visually analyze it"
  - "action=info returns only file metadata (format, size, dimensions) without image injection"
  - "If PIL is installed, dimensions are reported; otherwise PNG dimensions are parsed from the header"
---

# image_reader

Read and analyze images on disk for multimodal models.

## Why this tool exists

Multimodal models (like Gemma 4, Qwen-VL, GPT-4o) can understand images, but they need the image data
passed in a specific multimodal content format. This tool reads image files and returns metadata + path,
then the agent loop in main.py automatically injects the base64 image as a multimodal content part
so the model can actually see and analyze the image.

## Actions

### `read` (default)
Returns:
- File metadata (path, format, MIME type, size, dimensions)
- A path marker that triggers automatic image injection

Use this when you need to actually see/analyze the image content.

### `info`
Returns only metadata without triggering image injection. Use this to quickly check image properties.

## How it works

1. You call `image_reader` with `action=read`
2. The tool returns metadata + the file path
3. The agent loop detects the image marker and converts it to a multimodal content message:
   ```
   content: [
     {type: "text", text: "metadata..."},
     {type: "image_url", image_url: {url: "data:image/png;base64,..."}}
   ]
   ```
4. The model receives the image and can visually analyze it

## Parameters

| Name | Type | Required | Default | Description |
|------|------|----------|---------|-------------|
| path | string | yes | - | Image file path (absolute or relative to project) |
| action | string | no | read | `read` (visual analysis) or `info` (metadata only) |
