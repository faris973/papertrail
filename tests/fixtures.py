"""Small deterministic documents for rendering and indexing acceptance tests."""
from pypdf import PdfWriter
from pypdf.generic import DictionaryObject, NameObject, DecodedStreamObject


def make_pdf(path):
    writer = PdfWriter()
    sections = [
        ('Purchase receipt', 'Order PT-2026-0148', 'Laptop computer', 'Amount paid: USD 1,249.00', 'Purchased on 7 November 2026', 'Keep this receipt with your coverage documents.'),
        ('Warranty coverage', 'Your laptop warranty', 'Coverage period: 24 months from purchase.', 'Battery replacement is included during the first year.', 'Accidental damage is excluded.', 'For service, include your receipt and serial number.'),
        ('Making a claim', 'Warranty service request', 'Describe the fault and include your purchase receipt.', 'Back up your data before returning the device.', 'A service agent will confirm the next steps.', 'Reference: PT-2026-0148'),
    ]
    for n, lines in enumerate(sections, 1):
        page = writer.add_blank_page(width=595, height=842)
        page[NameObject('/Resources')] = DictionaryObject({NameObject('/Font'): DictionaryObject({NameObject('/F1'): DictionaryObject({NameObject('/Type'): NameObject('/Font'), NameObject('/Subtype'): NameObject('/Type1'), NameObject('/BaseFont'): NameObject('/Helvetica')})})})
        commands = ['0.98 0.975 0.95 rg 0 0 595 842 re f', '0.3 0.36 0.25 rg', 'BT /F1 10 Tf 48 790 Td (PAPERTRAIL  /  EXAMPLE DOCUMENT) Tj ET', '0.86 0.88 0.82 RG 48 770 m 547 770 l S']
        for i, line in enumerate(lines):
            size = 29 if i == 0 else 13
            y = 712 if i == 0 else 645 - (i - 1) * 35
            commands.append(f'BT /F1 {size} Tf 48 {y} Td ({line}) Tj ET')
        commands.append(f'BT /F1 10 Tf 48 45 Td (Example only - Page {n} of 3) Tj ET')
        stream = DecodedStreamObject();stream.set_data('\n'.join(commands).encode('ascii'))
        page[NameObject('/Contents')] = writer._add_object(stream)
    with open(path, 'wb') as output:
        writer.write(output)
