from __future__ import annotations

import shutil
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


ROOT = Path(__file__).resolve().parent
OUTPUT_CLEANED = ROOT / "offense_against_ai_arts_architecture_cleaned.png"
OUTPUT_LATEST = ROOT / "offense_against_ai_arts_architecture_latest.png"

WIDTH = 2000
HEIGHT = 1200

NAVY = (17, 26, 112)
GREEN = (0, 82, 68)
RED = (156, 18, 24)
ORANGE = (176, 105, 0)
BLACK = (22, 22, 22)
GRAY = (92, 98, 112)
LIGHT_BLUE = (247, 249, 255)
LIGHT_GREEN = (246, 255, 251)
LIGHT_RED = (255, 247, 247)
LIGHT_ORANGE = (255, 249, 239)
WHITE = (255, 255, 255)
SHADOW = (224, 227, 235)


def font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    path = "C:/Windows/Fonts/arialbd.ttf" if bold else "C:/Windows/Fonts/arial.ttf"
    return ImageFont.truetype(path, size)


TITLE = font(58, True)
BAND = font(24, True)
BOX_TITLE = font(24, True)
BOX_TEXT = font(20)
SMALL = font(17)


def text_size(draw: ImageDraw.ImageDraw, text: str, fnt: ImageFont.FreeTypeFont) -> tuple[int, int]:
    bbox = draw.textbbox((0, 0), text, font=fnt)
    return bbox[2] - bbox[0], bbox[3] - bbox[1]


def wrap_lines(draw: ImageDraw.ImageDraw, text: str, max_width: int, fnt: ImageFont.FreeTypeFont) -> list[str]:
    lines: list[str] = []
    for source_line in text.splitlines():
        words = source_line.split()
        if not words:
            lines.append("")
            continue
        current: list[str] = []
        for word in words:
            candidate = " ".join([*current, word])
            if text_size(draw, candidate, fnt)[0] <= max_width or not current:
                current.append(word)
            else:
                lines.append(" ".join(current))
                current = [word]
        if current:
            lines.append(" ".join(current))
    return lines


def draw_centered_lines(
    draw: ImageDraw.ImageDraw,
    rect: tuple[int, int, int, int],
    lines: list[str],
    fnt: ImageFont.FreeTypeFont,
    fill: tuple[int, int, int] = BLACK,
    gap: int = 6,
) -> None:
    x1, y1, x2, y2 = rect
    heights = [text_size(draw, line, fnt)[1] for line in lines]
    total_h = sum(heights) + gap * max(0, len(lines) - 1)
    y = y1 + ((y2 - y1) - total_h) / 2
    for line, h in zip(lines, heights):
        w, _ = text_size(draw, line, fnt)
        draw.text((x1 + ((x2 - x1) - w) / 2, y), line, font=fnt, fill=fill)
        y += h + gap


def box(
    draw: ImageDraw.ImageDraw,
    rect: tuple[int, int, int, int],
    title: str,
    body: str,
    outline: tuple[int, int, int],
    fill: tuple[int, int, int],
    title_color: tuple[int, int, int] | None = None,
    title_size: int = 24,
    body_size: int = 20,
) -> None:
    x1, y1, x2, y2 = rect
    draw.rounded_rectangle((x1 + 5, y1 + 6, x2 + 5, y2 + 6), radius=8, fill=SHADOW, outline=None)
    draw.rounded_rectangle(rect, radius=8, fill=fill, outline=outline, width=3)

    title_font = font(title_size, True)
    body_font = font(body_size)
    title_lines = wrap_lines(draw, title, x2 - x1 - 30, title_font)
    body_lines = wrap_lines(draw, body, x2 - x1 - 30, body_font)

    title_h = sum(text_size(draw, line, title_font)[1] for line in title_lines) + 5 * max(0, len(title_lines) - 1)
    title_y = y1 + 16
    for line in title_lines:
        w, h = text_size(draw, line, title_font)
        draw.text((x1 + ((x2 - x1) - w) / 2, title_y), line, font=title_font, fill=title_color or outline)
        title_y += h + 5

    body_top = y1 + 22 + title_h
    draw_centered_lines(draw, (x1 + 15, body_top, x2 - 15, y2 - 12), body_lines, body_font, BLACK, gap=6)


def table_box(draw: ImageDraw.ImageDraw, rect: tuple[int, int, int, int], title: str, rows: list[str]) -> None:
    x1, y1, x2, y2 = rect
    draw.rounded_rectangle((x1 + 5, y1 + 6, x2 + 5, y2 + 6), radius=8, fill=SHADOW, outline=None)
    draw.rounded_rectangle(rect, radius=8, fill=(252, 252, 252), outline=BLACK, width=3)
    header_h = 48
    draw.rectangle((x1, y1, x2, y1 + header_h), fill=WHITE, outline=BLACK, width=2)
    draw_centered_lines(draw, (x1, y1, x2, y1 + header_h), [title], BOX_TITLE, BLACK)
    row_h = (y2 - y1 - header_h) / len(rows)
    for idx, row in enumerate(rows):
        top = int(y1 + header_h + idx * row_h)
        bottom = int(y1 + header_h + (idx + 1) * row_h)
        draw.rectangle((x1, top, x2, bottom), fill=(252, 252, 252), outline=BLACK, width=1)
        draw_centered_lines(draw, (x1 + 8, top, x2 - 8, bottom), wrap_lines(draw, row, x2 - x1 - 16, BOX_TEXT), BOX_TEXT)


def center(rect: tuple[int, int, int, int]) -> tuple[int, int]:
    x1, y1, x2, y2 = rect
    return ((x1 + x2) // 2, (y1 + y2) // 2)


def edge(rect: tuple[int, int, int, int], side: str) -> tuple[int, int]:
    x1, y1, x2, y2 = rect
    if side == "left":
        return (x1, (y1 + y2) // 2)
    if side == "right":
        return (x2, (y1 + y2) // 2)
    if side == "top":
        return ((x1 + x2) // 2, y1)
    return ((x1 + x2) // 2, y2)


def arrow(
    draw: ImageDraw.ImageDraw,
    start: tuple[int, int],
    end: tuple[int, int],
    color: tuple[int, int, int] = BLACK,
    width: int = 3,
    dashed: bool = False,
) -> None:
    import math

    x1, y1 = start
    x2, y2 = end
    if dashed:
        segments = 16
        for idx in range(segments):
            if idx % 2 == 0:
                sx = x1 + (x2 - x1) * idx / segments
                sy = y1 + (y2 - y1) * idx / segments
                ex = x1 + (x2 - x1) * (idx + 1) / segments
                ey = y1 + (y2 - y1) * (idx + 1) / segments
                draw.line((sx, sy, ex, ey), fill=color, width=width)
    else:
        draw.line((start, end), fill=color, width=width)

    angle = math.atan2(y2 - y1, x2 - x1)
    head_len = 16
    head_angle = 0.5
    p1 = (x2 - head_len * math.cos(angle - head_angle), y2 - head_len * math.sin(angle - head_angle))
    p2 = (x2 - head_len * math.cos(angle + head_angle), y2 - head_len * math.sin(angle + head_angle))
    draw.polygon([end, p1, p2], fill=color)


def elbow(
    draw: ImageDraw.ImageDraw,
    points: list[tuple[int, int]],
    color: tuple[int, int, int] = BLACK,
    width: int = 3,
    dashed: bool = False,
) -> None:
    for idx in range(len(points) - 2):
        a = points[idx]
        b = points[idx + 1]
        if dashed:
            arrow(draw, a, b, color=color, width=width, dashed=True)
        else:
            draw.line((a, b), fill=color, width=width)
    arrow(draw, points[-2], points[-1], color=color, width=width, dashed=dashed)


def band_label(draw: ImageDraw.ImageDraw, text: str, y: int) -> None:
    w, h = text_size(draw, text, BAND)
    x = (WIDTH - w) / 2
    draw.rounded_rectangle((x - 12, y - 4, x + w + 12, y + h + 8), radius=6, fill=WHITE, outline=None)
    draw.text((x, y), text, font=BAND, fill=NAVY)


def main() -> None:
    image = Image.new("RGB", (WIDTH, HEIGHT), WHITE)
    draw = ImageDraw.Draw(image)

    title = "OFFENSE AGAINST THE AI ARTS"
    title_w, _ = text_size(draw, title, TITLE)
    draw.text(((WIDTH - title_w) / 2, 24), title, font=TITLE, fill=BLACK)

    config = (70, 120, 360, 245)
    dossiers = (430, 120, 760, 245)
    knowledge = (830, 120, 1160, 245)
    llm = (1255, 120, 1585, 245)
    optional = (1640, 120, 1930, 245)

    box(draw, config, "Operator & Runtime Config", "TARGET_APP / URL / token\nProfiles and environment", BLACK, WHITE, title_color=BLACK, title_size=22)
    box(draw, dossiers, "Target Dossiers & Playbooks", "Objectives, assets, roles\nSuccess markers\nFallback templates", GREEN, LIGHT_GREEN, title_color=GREEN, title_size=22)
    box(draw, knowledge, "Security Knowledge Base", "Ingested docs and local notes\nChroma / RAG corpus\nSupplied to planner context", GREEN, LIGHT_GREEN, title_color=GREEN, title_size=22)
    box(draw, llm, "LLM Backend", "OpenRouter / Ariadne\nPowers AI agents", NAVY, LIGHT_BLUE, title_color=NAVY, title_size=24)
    box(draw, optional, "Optional Surface Summary", "Profile summary by default\nActive probes opt-in only", GRAY, (248, 248, 248), title_color=GRAY, title_size=21)

    band_label(draw, "FINAL CAMPAIGN ROUND", 285)

    strategist = (90, 350, 430, 520)
    runner = (545, 350, 920, 520)
    adapters = (1040, 360, 1335, 510)
    target = (1500, 350, 1880, 520)

    box(draw, strategist, "1  STRATEGIST AGENT", "AI-generated objective-first attack plan\nReturns JSON prompt batch\nNo tool calls", NAVY, LIGHT_BLUE, title_color=NAVY, title_size=23)
    box(draw, runner, "2  DETERMINISTIC EXECUTION RUNNER", "Parses and validates plan\nFalls back if planner output is invalid\nCaptures raw evidence", BLACK, WHITE, title_color=BLACK, title_size=22)
    table_box(draw, adapters, "Execution Adapters", ["Direct HTTP default", "Promptfoo CLI optional", "Gandalf CTF benchmark"])
    box(draw, target, "TARGET AGENTIC AI SYSTEM", "Chat/API endpoint\nTools and guardrails\nApplication data/context", RED, LIGHT_RED, title_color=RED, title_size=23)

    # Context arrows into the strategist.
    arrow(draw, edge(config, "bottom"), (210, 350), BLACK)
    arrow(draw, edge(dossiers, "bottom"), (285, 350), GREEN)
    arrow(draw, edge(knowledge, "bottom"), (345, 350), GREEN)

    # Main execution flow.
    arrow(draw, edge(strategist, "right"), edge(runner, "left"), BLACK)
    arrow(draw, edge(runner, "right"), edge(adapters, "left"), BLACK)
    arrow(draw, edge(adapters, "right"), edge(target, "left"), BLACK)
    arrow(draw, (1500, 480), (1335, 480), BLACK)
    arrow(draw, (1040, 480), (920, 480), BLACK)

    band_label(draw, "ANALYSIS AND FEEDBACK", 570)

    analyzer = (330, 630, 700, 790)
    classifier = (820, 630, 1210, 790)
    feedback = (590, 875, 1160, 970)
    state = (1250, 855, 1495, 960)
    memory = (1530, 855, 1785, 960)

    box(draw, analyzer, "3  RESPONSE ANALYZER AGENT", "AI review of real executor logs\nOutcomes and guardrails\nObjective evidence", NAVY, LIGHT_BLUE, title_color=NAVY, title_size=22)
    box(draw, classifier, "DETERMINISTIC EVIDENCE CLASSIFIER", "Target-specific markers\nObjective/category counts\nConservative FULL_LEAK oracle", GREEN, LIGHT_GREEN, title_color=GREEN, title_size=21)
    box(draw, feedback, "Adaptive Feedback Controller", "Refine objectives, update coverage, decide stop criteria", GREEN, LIGHT_GREEN, title_color=GREEN, title_size=24)
    box(draw, state, "Planner State & Coverage", "Target objectives\nTaxonomy status", GREEN, LIGHT_GREEN, title_color=GREEN, title_size=20)
    box(draw, memory, "Experiential Memory", "High-confidence\nsuccessful vectors", GREEN, LIGHT_GREEN, title_color=GREEN, title_size=20)

    # Raw evidence from runner to analysis components.
    elbow(draw, [(735, 520), (735, 585), (515, 585), edge(analyzer, "top")], BLACK)
    elbow(draw, [(735, 520), (735, 585), (1015, 585), edge(classifier, "top")], BLACK)
    arrow(draw, edge(analyzer, "bottom"), (760, 875), NAVY)
    arrow(draw, edge(classifier, "bottom"), (990, 875), GREEN)
    arrow(draw, edge(feedback, "right"), edge(state, "left"), GREEN)
    elbow(draw, [edge(feedback, "right"), (1215, 920), (1215, 820), (1658, 820), edge(memory, "top")], GREEN)

    # Adaptive next-round route, kept outside the central boxes.
    elbow(draw, [(590, 925), (55, 925), (55, 435), edge(strategist, "left")], GREEN, dashed=True)
    draw.text((70, 705), "NEXT ROUND", font=SMALL, fill=GREEN)

    band_label(draw, "REPORTING", 1010)

    reporter = (70, 1045, 350, 1145)
    evidence = (520, 1035, 1010, 1155)
    archive = (1190, 1045, 1455, 1145)
    legend = (1600, 1030, 1930, 1150)

    box(draw, reporter, "REPORTER AGENT", "AI narrative only\nNo transcript rewriting", NAVY, LIGHT_BLUE, title_color=NAVY, title_size=21)
    box(draw, evidence, "DETERMINISTIC EVIDENCE ASSEMBLY", "Full transcripts, statistics\nCompleteness validation", NAVY, LIGHT_BLUE, title_color=NAVY, title_size=21)
    box(draw, archive, "REPORT ARCHIVE", "PDF, HTML, JSON", NAVY, LIGHT_BLUE, title_color=NAVY, title_size=21)
    arrow(draw, edge(reporter, "right"), edge(evidence, "left"), BLACK)
    arrow(draw, edge(evidence, "right"), edge(archive, "left"), BLACK)
    elbow(draw, [(1015, 790), (1015, 1005), (765, 1005), edge(evidence, "top")], GREEN)

    draw.rounded_rectangle(legend, radius=6, fill=WHITE, outline=BLACK, width=2)
    draw.line((1630, 1070, 1690, 1070), fill=BLACK, width=3)
    draw.text((1710, 1058), "Solid: data flow", font=SMALL, fill=BLACK)
    arrow(draw, (1630, 1110), (1690, 1110), GREEN, dashed=True)
    draw.text((1710, 1098), "Dashed: adaptive/optional", font=SMALL, fill=BLACK)

    footer = "Updated after replacing the LLM executor with a deterministic execution runner and fallback plan generation"
    footer_w, _ = text_size(draw, footer, SMALL)
    draw.text(((WIDTH - footer_w) / 2, 1172), footer, font=SMALL, fill=GRAY)

    image.save(OUTPUT_CLEANED)
    shutil.copyfile(OUTPUT_CLEANED, OUTPUT_LATEST)
    print(f"Wrote {OUTPUT_CLEANED}")
    print(f"Wrote {OUTPUT_LATEST}")


if __name__ == "__main__":
    main()
