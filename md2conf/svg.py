"""
SVG dimension extraction utilities.

Copyright 2022-2025, Levente Hunyadi

:see: https://github.com/hunyadi/md2conf
"""

import logging
import re
from pathlib import Path

import lxml.etree as ET

LOGGER = logging.getLogger(__name__)

SVG_NAMESPACE = "http://www.w3.org/2000/svg"


def _extract_dimensions_from_root(root: ET._Element) -> tuple[int | None, int | None]:
    """
    Extracts width and height from an SVG root element.

    Attempts to read dimensions from:
    1. Explicit width/height attributes on the root <svg> element
    2. The viewBox attribute if width/height are not specified

    :param root: The root element of the SVG document.
    :returns: A tuple of (width, height) in pixels, or (None, None) if dimensions cannot be determined.
    """

    # Handle namespaced and non-namespaced SVG
    if root.tag != f"{{{SVG_NAMESPACE}}}svg" and root.tag != "svg":
        return None, None

    width_attr = root.get("width")
    height_attr = root.get("height")

    width = _parse_svg_length(width_attr) if width_attr else None
    height = _parse_svg_length(height_attr) if height_attr else None

    # If width/height not specified, try to derive from viewBox
    if width is None or height is None:
        viewbox = root.get("viewBox")
        if viewbox:
            vb_width, vb_height = _parse_viewbox(viewbox)
            if width is None:
                width = vb_width
            if height is None:
                height = vb_height

    return width, height


def get_svg_dimensions(path: Path) -> tuple[int | None, int | None]:
    """
    Extracts width and height from an SVG file.

    Attempts to read dimensions from:
    1. Explicit width/height attributes on the root <svg> element
    2. The viewBox attribute if width/height are not specified

    :param path: Path to the SVG file.
    :returns: A tuple of (width, height) in pixels, or (None, None) if dimensions cannot be determined.
    """

    try:
        tree = ET.parse(str(path))
        root = tree.getroot()
        width, height = _extract_dimensions_from_root(root)
        if width is None and height is None:
            LOGGER.warning("SVG file %s does not have an <svg> root element", path)
        return width, height

    except ET.XMLSyntaxError as ex:
        LOGGER.warning("Failed to parse SVG file %s: %s", path, ex)
        return None, None
    except Exception as ex:
        LOGGER.warning("Unexpected error reading SVG dimensions from %s: %s", path, ex)
        return None, None


def get_svg_dimensions_from_bytes(data: bytes) -> tuple[int | None, int | None]:
    """
    Extracts width and height from SVG data in memory.

    Attempts to read dimensions from:
    1. Explicit width/height attributes on the root <svg> element
    2. The viewBox attribute if width/height are not specified

    :param data: The SVG content as bytes.
    :returns: A tuple of (width, height) in pixels, or (None, None) if dimensions cannot be determined.
    """

    try:
        root = ET.fromstring(data)
        return _extract_dimensions_from_root(root)

    except ET.XMLSyntaxError as ex:
        LOGGER.warning("Failed to parse SVG data: %s", ex)
        return None, None
    except Exception as ex:
        LOGGER.warning("Unexpected error reading SVG dimensions from data: %s", ex)
        return None, None


def _serialize_svg_opening_tag(root: ET._Element) -> str:
    """
    Serializes just the opening tag of an SVG element (without children or closing tag).

    :param root: The root SVG element.
    :returns: The opening tag string, e.g., '<svg width="100" height="200" ...>'.
    """
    # Build the opening tag from element name and attributes
    tag_name = root.tag
    # Handle namespaced tag - extract local name for the tag but preserve namespace declarations
    if tag_name.startswith("{"):
        # Extract namespace and local name
        ns_end = tag_name.index("}")
        tag_name = "svg"  # Use simple tag name; namespace will be in attributes

    parts = [f"<{tag_name}"]

    # Add namespace declarations (nsmap)
    for prefix, uri in root.nsmap.items():
        if prefix is None:
            parts.append(f' xmlns="{uri}"')
        else:
            parts.append(f' xmlns:{prefix}="{uri}"')

    # Add attributes
    for name, value in root.attrib.items():
        # Handle namespaced attributes
        if name.startswith("{"):
            ns_end = name.index("}")
            ns_uri = name[1:ns_end]
            local_name = name[ns_end + 1 :]
            # Find prefix for this namespace
            prefix = None
            for p, u in root.nsmap.items():
                if u == ns_uri and p is not None:
                    prefix = p
                    break
            if prefix:
                parts.append(f' {prefix}:{local_name}="{value}"')
            else:
                parts.append(f' {local_name}="{value}"')
        else:
            parts.append(f' {name}="{value}"')

    parts.append(">")
    return "".join(parts)


def fix_svg_dimensions(data: bytes) -> bytes:
    """
    Fixes SVG data by setting explicit width/height attributes based on viewBox.

    Mermaid generates SVGs with width="100%" which Confluence doesn't handle well.
    This function replaces percentage-based dimensions with explicit pixel values
    derived from the viewBox.

    Uses lxml to parse and modify the root element's attributes, then replaces
    just the opening tag in the original document to preserve the rest exactly.

    :param data: The SVG content as bytes.
    :returns: The modified SVG content with explicit dimensions, or original data if modification fails.
    """

    try:
        text = data.decode("utf-8")

        # Parse the SVG to extract root element attributes
        root = ET.fromstring(data)

        # Verify it's an SVG element
        if root.tag != f"{{{SVG_NAMESPACE}}}svg" and root.tag != "svg":
            return data

        # Check if we need to fix (has width="100%" or similar percentage)
        width_attr = root.get("width")
        if width_attr != "100%":
            # Check if it already has a valid numeric width
            if width_attr is not None and _parse_svg_length(width_attr) is not None:
                return data  # Already has numeric width

        # Get viewBox dimensions
        viewbox = root.get("viewBox")
        if not viewbox:
            return data

        vb_width, vb_height = _parse_viewbox(viewbox)
        if vb_width is None or vb_height is None:
            return data

        # Extract the original opening tag from the text
        svg_tag_match = re.search(r"<svg\b[^>]*>", text)
        if not svg_tag_match:
            return data

        original_tag = svg_tag_match.group(0)

        # Modify the root element's attributes
        root.set("width", str(vb_width))

        # Set height if missing or if it's a percentage
        height_attr = root.get("height")
        if height_attr is None or height_attr == "100%":
            root.set("height", str(vb_height))

        # Clean up the style attribute - remove max-width which conflicts with explicit width
        # Mermaid sets style="max-width: Xpx; background-color: transparent;" which can
        # interfere with Confluence's rendering when we've set explicit dimensions
        style_attr = root.get("style")
        if style_attr:
            # Remove max-width from the style
            style_parts = [s.strip() for s in style_attr.split(";") if s.strip()]
            style_parts = [s for s in style_parts if not s.startswith("max-width")]
            if style_parts:
                root.set("style", "; ".join(style_parts))
            else:
                # Remove empty style attribute
                del root.attrib["style"]

        # Serialize just the opening tag with modified attributes
        new_tag = _serialize_svg_opening_tag(root)

        # Replace the original opening tag with the new one
        text = text.replace(original_tag, new_tag, 1)

        return text.encode("utf-8")

    except Exception as ex:
        LOGGER.warning("Unexpected error fixing SVG dimensions: %s", ex)
        return data


def _extract_text_lines_from_element(element: ET.Element) -> list[str]:
    """
    Recursively extracts text from an element, splitting on <br> tags and newlines.

    Handles:
    - <br> elements
    - Actual newline characters
    - Literal \\n escape sequences (two characters: backslash + n)

    :param element: The XML element to extract text from.
    :returns: A list of text lines.
    """
    lines: list[str] = []
    current_line: list[str] = []

    def flush_line() -> None:
        text = "".join(current_line).strip()
        if text:
            lines.append(text)
        current_line.clear()

    def split_on_newlines(text: str) -> list[str]:
        """Split text on both actual newlines and literal \\n sequences."""
        # First split on actual newlines, then split each part on literal \n
        result = []
        for part in text.split("\n"):
            # Split on literal \n (backslash followed by n)
            subparts = part.split("\\n")
            result.extend(subparts)
        return result

    def process_element(elem: ET.Element) -> None:
        # Check if this is a <br> element (in any namespace)
        local_name = elem.tag.split("}")[-1] if "}" in elem.tag else elem.tag
        if local_name.lower() == "br":
            flush_line()
            return

        # Add element's direct text
        if elem.text:
            # Split on newlines (both actual and literal \n)
            parts = split_on_newlines(elem.text)
            for i, part in enumerate(parts):
                current_line.append(part)
                if i < len(parts) - 1:
                    flush_line()

        # Process children
        for child in elem:
            process_element(child)
            # Add tail text (text after child element)
            if child.tail:
                parts = split_on_newlines(child.tail)
                for i, part in enumerate(parts):
                    current_line.append(part)
                    if i < len(parts) - 1:
                        flush_line()

    process_element(element)
    flush_line()  # Don't forget the last line

    return lines


def _estimate_text_width(text: str, font_size: float = 12.0) -> float:
    """
    Estimates the pixel width of text based on font size.

    Uses an average character width ratio for proportional fonts.
    This is an approximation since we don't have actual font metrics.

    :param text: The text to measure.
    :param font_size: The font size in pixels.
    :returns: Estimated width in pixels.
    """
    # Average character width is roughly 0.6x font size for proportional fonts
    # This works reasonably well for common fonts like Trebuchet MS, Verdana, Arial
    avg_char_width = font_size * 0.6
    return len(text) * avg_char_width


def _word_wrap_text(text: str, max_width: float, font_size: float = 12.0) -> list[str]:
    """
    Wraps text to fit within a maximum pixel width.

    :param text: The text to wrap.
    :param max_width: Maximum width in pixels.
    :param font_size: The font size in pixels.
    :returns: List of wrapped lines.
    """
    if max_width <= 0:
        return [text]

    # If text already fits, return as-is
    if _estimate_text_width(text, font_size) <= max_width:
        return [text]

    words = text.split()
    if not words:
        return [text]

    lines = []
    current_line: list[str] = []
    current_width = 0.0
    space_width = _estimate_text_width(" ", font_size)

    for word in words:
        word_width = _estimate_text_width(word, font_size)

        # Check if adding this word would exceed max width
        new_width = current_width + (space_width if current_line else 0) + word_width

        if new_width <= max_width or not current_line:
            # Add word to current line
            current_line.append(word)
            current_width = new_width
        else:
            # Start a new line
            lines.append(" ".join(current_line))
            current_line = [word]
            current_width = word_width

    # Don't forget the last line
    if current_line:
        lines.append(" ".join(current_line))

    return lines


def convert_foreign_object_to_text(data: bytes) -> bytes:
    """
    Converts foreignObject elements containing XHTML to native SVG text elements.

    Mermaid uses foreignObject with embedded XHTML for text rendering in some diagram
    types (ERD, Class diagrams). Confluence cannot render this XHTML content, so this
    function converts them to native SVG <text> elements.

    Multi-line text (via <br> tags or \\n) is converted to multiple <tspan> elements.
    Long text is automatically word-wrapped to fit within the foreignObject width.

    :param data: The SVG content as bytes.
    :returns: The modified SVG content with foreignObject replaced by text elements.
    """

    try:
        root = ET.fromstring(data)

        # Find all foreignObject elements
        foreign_objects = list(root.iter(f"{{{SVG_NAMESPACE}}}foreignObject"))
        if not foreign_objects:
            return data  # No foreignObject elements, return unchanged

        font_size = 12.0  # pixels - matches the style we set on text elements

        for fo in foreign_objects:
            # Extract text lines from the XHTML inside foreignObject
            lines = _extract_text_lines_from_element(fo)
            if not lines:
                continue

            # Get foreignObject dimensions and position
            fo_width = float(fo.get("width", "0"))
            fo_height = float(fo.get("height", "0"))
            fo_x = float(fo.get("x", "0"))
            fo_y = float(fo.get("y", "0"))

            # Word-wrap lines to fit within the foreignObject width
            # Use slightly less than full width to add some padding
            wrap_width = fo_width * 0.95 if fo_width > 0 else 0
            wrapped_lines: list[str] = []
            for line in lines:
                wrapped_lines.extend(_word_wrap_text(line, wrap_width, font_size))

            # Find the parent group element
            parent = fo.getparent()
            if parent is None:
                continue

            # Create SVG text element at center of foreignObject area
            text_elem = ET.Element(f"{{{SVG_NAMESPACE}}}text")
            center_x = fo_x + fo_width / 2
            text_elem.set("x", str(center_x))
            text_elem.set("text-anchor", "middle")
            text_elem.set("style", f"font-family: trebuchet ms, verdana, arial, sans-serif; font-size: {font_size}px; fill: #333;")

            # Calculate vertical positioning for multi-line text
            line_height = font_size + 2  # pixels (slightly more than font-size for readability)
            total_text_height = line_height * len(wrapped_lines)
            # Start y so that the block is vertically centered
            start_y = fo_y + (fo_height - total_text_height) / 2 + line_height * 0.8  # 0.8 adjusts for baseline

            if len(wrapped_lines) == 1:
                # Single line: use simple text element centered vertically
                text_elem.set("y", str(fo_y + fo_height / 2))
                text_elem.set("dominant-baseline", "middle")
                text_elem.text = wrapped_lines[0]
            else:
                # Multiple lines: use tspan elements
                for i, line in enumerate(wrapped_lines):
                    tspan = ET.SubElement(text_elem, f"{{{SVG_NAMESPACE}}}tspan")
                    tspan.set("x", str(center_x))
                    tspan.set("y", str(start_y + i * line_height))
                    tspan.text = line

            # Replace foreignObject with text element in the parent
            idx = list(parent).index(fo)
            parent.remove(fo)
            parent.insert(idx, text_elem)

        # Serialize back to bytes
        return ET.tostring(root, encoding="unicode").encode("utf-8")

    except Exception as ex:
        LOGGER.warning("Error converting foreignObject to text: %s", ex)
        return data


def _parse_svg_length(value: str) -> int | None:
    """
    Parses an SVG length value and converts it to pixels.

    Supports: px, pt, em, ex, in, cm, mm, pc, and unitless values.
    For simplicity, assumes 96 DPI and 16px base font size.

    :param value: The SVG length string (e.g., "100", "100px", "10em").
    :returns: The length in pixels as an integer, or None if parsing fails.
    """

    if not value:
        return None

    value = value.strip()

    # Match number with optional unit
    match = re.match(r"^([+-]?(?:\d+\.?\d*|\.\d+))(%|px|pt|em|ex|in|cm|mm|pc)?$", value, re.IGNORECASE)
    if not match:
        return None

    num_str, unit = match.groups()
    try:
        num = float(num_str)
    except ValueError:
        return None

    # Convert to pixels (assuming 96 DPI, 16px base font)
    match unit.lower() if unit else None:
        case None | "px":
            pixels = num
        case "pt":
            pixels = num * 96 / 72  # 1pt = 1/72 inch
        case "in":
            pixels = num * 96
        case "cm":
            pixels = num * 96 / 2.54
        case "mm":
            pixels = num * 96 / 25.4
        case "pc":
            pixels = num * 96 / 6  # 1pc = 12pt = 1/6 inch
        case "em":
            pixels = num * 16  # assume 16px base font
        case "ex":
            pixels = num * 8  # assume ex ≈ 0.5em
        case "%":
            # Percentage values can't be resolved without a container; skip
            return None
        case _:
            return None

    return int(round(pixels))


def _parse_viewbox(viewbox: str) -> tuple[int | None, int | None]:
    """
    Parses an SVG viewBox attribute and extracts width and height.

    :param viewbox: The viewBox string (e.g., "0 0 100 200").
    :returns: A tuple of (width, height) in pixels, or (None, None) if parsing fails.
    """

    if not viewbox:
        return None, None

    # viewBox format: "min-x min-y width height"
    # Values can be separated by whitespace and/or commas
    parts = re.split(r"[\s,]+", viewbox.strip())
    if len(parts) != 4:
        return None, None

    try:
        width = int(round(float(parts[2])))
        height = int(round(float(parts[3])))
        return width, height
    except ValueError:
        return None, None
