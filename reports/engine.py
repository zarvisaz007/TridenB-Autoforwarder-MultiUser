import json
import time
import asyncio
import urllib.request
from .config import REPORT_CONFIG


async def _ollama_analyze(messages_text, system_prompt):
    """Send text to Ollama for analysis. Runs in a thread to avoid blocking."""
    cfg = REPORT_CONFIG["ollama"]
    payload = {
        "model": cfg["model"],
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": messages_text},
        ],
        "stream": False,
        "keep_alive": cfg["keep_alive"],
    }
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(cfg["url"], data=data, headers={"Content-Type": "application/json"})

    def _request():
        with urllib.request.urlopen(req, timeout=cfg["timeout"]) as resp:
            result = json.loads(resp.read().decode("utf-8"))
            return result.get("message", {}).get("content", "").strip()

    return await asyncio.to_thread(_request)


def _format_messages_for_llm(messages):
    """Format DB message rows into a readable text block for the LLM."""
    lines = []
    for msg in messages:
        ts = time.strftime("%Y-%m-%d %H:%M", time.localtime(msg["timestamp"]))
        text = msg["text_content"].strip()
        if text:
            lines.append(f"[{ts}] {text}")
    return "\n\n".join(lines)


def _chunk_messages(messages, chunk_size):
    """Split messages into chunks that fit within the char limit."""
    chunks = []
    current_chunk = []
    current_size = 0

    for msg in messages:
        ts = time.strftime("%Y-%m-%d %H:%M", time.localtime(msg["timestamp"]))
        text = msg["text_content"].strip()
        if not text:
            continue
        entry = f"[{ts}] {text}"
        entry_size = len(entry) + 2  # +2 for \n\n separator

        if current_size + entry_size > chunk_size and current_chunk:
            chunks.append(current_chunk)
            current_chunk = []
            current_size = 0

        current_chunk.append(msg)
        current_size += entry_size

    if current_chunk:
        chunks.append(current_chunk)

    return chunks


async def generate_report(messages, report_type="summary", custom_prompt=None, progress_cb=None):
    """
    Generate a finance report from a list of message dicts.

    Args:
        messages: list of dicts with 'text_content' and 'timestamp' keys
        report_type: one of the keys in REPORT_CONFIG["report_types"]
        custom_prompt: used when report_type is "custom"
        progress_cb: optional callback(status_text) for progress updates

    Returns:
        str: the generated report in Markdown
    """
    if not messages:
        return "No messages to analyze."

    report_cfg = REPORT_CONFIG["report_types"].get(report_type)
    if not report_cfg:
        return f"Unknown report type: {report_type}"

    system_prompt = custom_prompt if report_type == "custom" else report_cfg["prompt"]
    if not system_prompt:
        return "No prompt provided for custom report."

    chunk_size = REPORT_CONFIG["chunk_size"]
    chunks = _chunk_messages(messages, chunk_size)

    if progress_cb:
        progress_cb(f"Analyzing {len(messages)} messages in {len(chunks)} chunk(s)...")

    if len(chunks) == 1:
        # Single chunk — direct analysis
        text_block = _format_messages_for_llm(chunks[0])
        report = await _ollama_analyze(text_block, system_prompt)
        return report

    # Multi-chunk: analyze each chunk, then synthesize
    partial_reports = []
    for i, chunk in enumerate(chunks):
        if progress_cb:
            progress_cb(f"  Analyzing chunk {i+1}/{len(chunks)} ({len(chunk)} messages)...")

        text_block = _format_messages_for_llm(chunk)
        chunk_prompt = (
            f"{system_prompt}\n\n"
            f"NOTE: This is chunk {i+1} of {len(chunks)}. "
            f"Provide analysis for this portion only. It will be combined later."
        )
        partial = await _ollama_analyze(text_block, chunk_prompt)
        partial_reports.append(partial)

        # Small delay between chunks to avoid RAM spike
        await asyncio.sleep(1)

    # Synthesize all partial reports into a final one
    if progress_cb:
        progress_cb("Synthesizing final report...")

    combined = "\n\n---\n\n".join(
        [f"### Chunk {i+1} Analysis\n{r}" for i, r in enumerate(partial_reports)]
    )

    synthesis_prompt = (
        f"{system_prompt}\n\n"
        "Below are partial analyses of different time periods. "
        "Combine them into ONE cohesive final report. Remove duplicates, "
        "merge tables, and provide an overall summary. Keep the same format."
    )

    final_report = await _ollama_analyze(combined, synthesis_prompt)
    return final_report
