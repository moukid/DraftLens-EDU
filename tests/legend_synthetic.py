"""Synthetic browser edge cases rendered by the production SVG serializer; no CAD files."""
from dataclasses import replace
import base64
import io
import json

import ezdxf

from app.finding_presentation import compact_finding_presentation
from app.svg_renderer import render_svg
from tests.test_review_usability_repairs import basic_snapshot


def browser_fixture():
    snapshot = basic_snapshot()
    review = snapshot.review_response
    drawing = snapshot.reviewed_drawing
    template = drawing.reference_entities[0]
    references = tuple(replace(template, entity_id=f'R-QA-{i}', source='reference', kind='line',
        layer=['reference', 'student', 'issues'][i % 3],
        points=((i % 16 * 20., i // 16 * 20.), (i % 16 * 20. + 16, i // 16 * 20. + 10)),
        bbox=None) for i in range(160))
    students = tuple(replace(e, entity_id=e.entity_id.replace('R-', 'S-'), source='student',
                            points=tuple((x,y+3) for x,y in e.points)) for e in references)
    roles = ['missing', 'extra', 'inaccurate', 'connectivity', 'warning', 'critical']
    records, visuals = [], []
    primary = next(i for i in review['issues'] if i['finding_role'] == 'primary')
    for index, role in enumerate(roles):
        identity = f'QA-{role}'
        records.append(dict(primary, issue_id=identity, visual_role=role,
            category='deliberately_unrelated_category',
            severity='critical' if role == 'critical' else 'minor',
            finding_role='supporting' if role == 'connectivity' else 'primary',
            blocking=role == 'warning', final_applied_contribution=0,
            technical_feedback=f'Synthetic {role} evidence',
            correction_guidance={'related_primary_issue_id':'QA-inaccurate'} if role == 'connectivity' else {}))
        visuals.append(replace(drawing.issues[0], issue_id=identity, visual_role=role,
            expected_geometry=references[index], actual_geometry=students[index],
            region=(index * 35., 40., index * 35. + 22, 65.)))
    # Selected evidence with no geometry must not misleadingly enable Locate.
    records.append(dict(records[-1], issue_id='QA-no-geometry', visual_role='warning',
                        severity='minor', blocking=False, finding_role='informational'))
    visuals.append(replace(visuals[-1], issue_id='QA-no-geometry', visual_role='warning',
                           region=None, expected_geometry=None, actual_geometry=None))
    review['issues'] = records
    review['unsupported_entities'] = {'reference':[], 'student':[{'entity_type':'HATCH','layer':'QA','handle':'QA-H'}]}
    review['finding_counts'] = {'primary_student_issues':5, 'supporting_findings':1,
                                'reference_validation_notes':0, 'unsupported_entities':1}
    review['finding_presentation'] = compact_finding_presentation(records, review['unsupported_entities'])
    review['svg'] = render_svg(replace(drawing, reference_entities=references, student_entities=students,
                                      issues=tuple(visuals), extents=(0.,0.,330.,210.)))
    return review


def dense_uploads():
    outputs = {}
    for student in (False, True):
        doc = ezdxf.new('R2010'); doc.units = 4
        model = doc.modelspace()
        for i in range(120):
            if student and i == 5:
                continue
            x, y = i % 12 * 30, i // 12 * 30
            model.add_line((x,y), (x+ (14 if student and i == 10 else 20),y+8))
        if student:
            model.add_circle((400,200), 5)
        stream = io.StringIO(); doc.write(stream)
        outputs['student' if student else 'reference'] = base64.b64encode(stream.getvalue().encode()).decode()
    return outputs


if __name__ == '__main__':
    print(json.dumps({'review':browser_fixture(), 'uploads':dense_uploads()}))
