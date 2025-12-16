"""
Publish Markdown files to Confluence wiki.

Copyright 2022-2025, Levente Hunyadi

:see: https://github.com/hunyadi/md2conf
"""

import hashlib
import logging
import os
import os.path
import shutil
import subprocess
from dataclasses import dataclass
from typing import Literal

LOGGER = logging.getLogger(__name__)


@dataclass
class MermaidConfigProperties:
    """
    Configuration options for rendering Mermaid diagrams.

    :param scale: Scaling factor for the rendered diagram.
    :param background_color: Background color for the rendered diagram (default: 'transparent').
    """

    scale: float | None = None
    background_color: str = "transparent"


def is_docker() -> bool:
    "True if the application is running in a Docker container."

    return os.environ.get("CHROME_BIN") == "/usr/bin/chromium-browser" and os.environ.get("PUPPETEER_SKIP_DOWNLOAD") == "true"


def get_mmdc() -> str:
    "Path to the Mermaid diagram converter."

    if is_docker():
        full_path = "/home/md2conf/node_modules/.bin/mmdc"
        if os.path.exists(full_path):
            return full_path
        else:
            return "mmdc"
    elif os.name == "nt":
        return "mmdc.cmd"
    else:
        return "mmdc"


def has_mmdc() -> bool:
    "True if Mermaid diagram converter is available on the OS."

    executable = get_mmdc()
    return shutil.which(executable) is not None


def render_diagram(source: str, output_format: Literal["png", "svg"] = "png", config: MermaidConfigProperties | None = None) -> bytes:
    """
    Generates a PNG or SVG image from a Mermaid diagram source.

    For SVG output, a unique ID is generated based on the source content hash.
    This ensures that when multiple Mermaid diagrams are embedded on the same
    page, each has unique element IDs and CSS selectors, preventing conflicts.
    """

    if config is None:
        config = MermaidConfigProperties()

    # Generate a unique SVG ID based on content hash to avoid ID conflicts
    # when multiple diagrams are on the same page. Mermaid uses this ID as
    # a prefix for all internal element IDs and CSS selectors.
    source_hash = hashlib.md5(source.encode("utf-8")).hexdigest()[:8]
    svg_id = f"mermaid-{source_hash}"

    cmd = [
        get_mmdc(),
        "--input",
        "-",
        "--output",
        "-",
        "--outputFormat",
        output_format,
        "--backgroundColor",
        config.background_color,
        "--scale",
        str(config.scale or 2),
        "--svgId",
        svg_id,
    ]
    root = os.path.dirname(__file__)
    if is_docker():
        cmd.extend(["-p", os.path.join(root, "puppeteer-config.json")])
    LOGGER.debug("Executing: %s", " ".join(cmd))

    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stdin=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=False,
    )
    stdout, stderr = proc.communicate(input=source.encode("utf-8"))
    if proc.returncode:
        messages = [f"failed to convert Mermaid diagram; exit code: {proc.returncode}"]
        console_output = stdout.decode("utf-8")
        if console_output:
            messages.append(f"output:\n{console_output}")
        console_error = stderr.decode("utf-8")
        if console_error:
            messages.append(f"error:\n{console_error}")
        raise RuntimeError("\n".join(messages))

    return stdout
