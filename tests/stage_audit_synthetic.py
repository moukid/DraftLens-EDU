"""Procedural, non-private uploads for the independent live stage audit."""
import base64
import io
import json
import ezdxf


def document(*, tags=False, units=4, gap=0):
    doc = ezdxf.new("R2010")
    doc.units = units
    model = doc.modelspace()
    for a, b in [((0, 0), (100, 0)), ((100, gap), (100, 80)),
                 ((100, 80), (0, 80)), ((0, 80), (0, 0)),
                 ((10, 10), (23, 15)), ((40, 20), (62, 31)), ((60, 55), (78, 61))]:
        model.add_line(a, b, dxfattribs={"layer": "GEOMETRY"})
    model.add_arc((30, 45), 8, 0, 90, dxfattribs={"layer": "GEOMETRY"})
    if tags:
        for code, point in [("D1", (50, 0)), ("W1", (50, 2)), ("X9", (80, 70))]:
            model.add_text(code, dxfattribs={"layer": "dL-iNfO-tags", "insert": point})
        model.add_text("D1", dxfattribs={"layer": "DL-INFO-LEGEND", "insert": (180, 180)})
        model.add_text("Instructor notes", dxfattribs={"layer": "DL-Info-Notes", "insert": (200, 200)})
    stream = io.StringIO()
    doc.write(stream)
    return stream.getvalue().encode()


if __name__ == "__main__":
    print(json.dumps({key: base64.b64encode(data).decode() for key, data in {
        "reference": document(tags=True), "student": document(),
        "cm": document(units=5), "gap": document(gap=4)
    }.items()}))
