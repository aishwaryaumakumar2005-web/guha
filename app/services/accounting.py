from datetime import datetime, date
from io import BytesIO
import os
from fpdf import FPDF
from app.extensions import db
from .payment_methods import TALLY_ACCOUNT_FOR_METHOD, classify_method

LOGO_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        'static', 'uploads', 'yazh_academy_logo.png')
BILL_NOTE = ("In our acclaimed training division, we proudly present variety of "
             "skill development courses designed to meet the changing market demands.")


def _safe_pct(raw, default=9.0):
    """Parse a GST percentage setting; fall back on blanks/garbage."""
    try:
        val = float((raw or '').strip() if isinstance(raw, str) else raw)
        if 0 <= val <= 100:
            return val
    except (TypeError, ValueError):
        pass
    return default


def build_invoice_item_rows(desc, has_gst, hsn, taxable, cgst, sgst, total):
    """Build the invoice items table rows for one receipt.

    Always a single installment row valued from the stored split, so the
    items trivially sum to the totals row. Pure function — the W1
    reconciliation guarantee is unit-tested here, not inside the PDF bytes.
    """
    if has_gst:
        return [[desc, hsn, f'Rs. {taxable:,.2f}', f'Rs. {cgst:,.2f}',
                 f'Rs. {sgst:,.2f}', f'Rs. {total:,.2f}']]
    return [[desc, hsn, f'Rs. {taxable:,.2f}', f'Rs. {total:,.2f}']]


class AccountingService:
    def __init__(self, app=None):
        self.app = app
        if app:
            self.init_app(app)

    def init_app(self, app):
        self.app = app

    def _get_settings(self):
        from app.models import SystemSetting
        def val(key):
            s = SystemSetting.query.filter_by(key=key).first()
            return s.value if s and s.value else ''
        return {
            'org_name': val('ORG_NAME') or 'Guha India',
            'org_address': val('ORG_ADDRESS') or '1st floor, KKG Complex, SPT Mani Nagar, Gandhi Nagar Post, Arch Gate, Neyveli, Tamilnadu 607308, India',
            'org_gstin': val('ORG_GSTIN') or '33ABAFG1922E1Z2',
            'org_mobile': val('ORG_MOBILE') or '8248779596',
            'org_email': val('ORG_EMAIL') or 'md@guhaindia.in',
            'org_hsn': val('ORG_HSN') or '999293',
            'org_state': val('ORG_STATE') or 'Tamil Nadu',
            'org_state_code': val('ORG_STATE_CODE') or '33',
            'cgst_pct': _safe_pct(val('CGST_PCT')),
            'sgst_pct': _safe_pct(val('SGST_PCT')),
            'invoice_prefix': val('INVOICE_PREFIX') or 'INV',
        }

    def _next_invoice_number(self):
        from app.models import SystemSetting
        s = SystemSetting.query.filter_by(key='_LAST_INVOICE_NO').first()
        last = int(s.value) if s and s.value else 0
        next_no = last + 1
        if s:
            s.value = str(next_no)
        else:
            db.session.add(SystemSetting(key='_LAST_INVOICE_NO', value=str(next_no)))
        db.session.commit()
        cfg = self._get_settings()
        year = date.today().year
        return f"{cfg['invoice_prefix']}-{year}-{next_no:04d}"

    @staticmethod
    def invoice_item_description(fee_record, max_len=40):
        """One-line description for the invoice items table.

        Names the installment (not full course fees — see W1) and truncates
        to fit the fixed-width PDF description cell, which cannot wrap.
        Pure function so the reconciling logic is directly unit-testable.
        """
        courses = list(fee_record.student.courses) if fee_record.student else []
        names = ', '.join(c.name for c in courses)
        if not names:
            return "Course fee installment"

        # Keep the closing bracket visible when long course names are shortened.
        prefix = "Course fee installment ("
        suffix = ")"
        full_desc = f"{prefix}{names}{suffix}"
        if len(full_desc) <= max_len:
            return full_desc
        available = max(1, max_len - len(prefix) - len(suffix) - 3)
        return f"{prefix}{names[:available].rstrip()}...{suffix}"

    def generate_invoice_pdf(self, fee_record):
        cfg = self._get_settings()
        from .account_service import company_bill_name
        company = fee_record.company
        student = fee_record.student
        courses = list(student.courses)
        if company is not None:
            has_gst = bool(company.is_gst_registered)
        else:
            # Legacy company-less rows: GST profile from the agreed snapshot.
            from .account_service import agreed_enrollment_items
            has_gst = any(it['gst_applicable'] for it in agreed_enrollment_items(student.id))
        total_fee = sum(c.fees for c in courses)

        if has_gst:
            if fee_record.taxable_amount:
                # Reprint-safe: reuse the booked split so a later rate change
                # can never rewrite this invoice. CGST == SGST intra-state.
                total = fee_record.amount_paid
                taxable = fee_record.taxable_amount
                _gst = fee_record.gst_amount or 0.0
                cgst = round(_gst / 2, 2)
                sgst = round(_gst - cgst, 2)
            else:
                # Legacy rows booked before splits were stored.
                total_pct = cfg['cgst_pct'] + cfg['sgst_pct']
                total = fee_record.amount_paid
                taxable = round(total * 100 / (100 + total_pct), 2)
                cgst = round(taxable * cfg['cgst_pct'] / 100, 2)
                sgst = round(taxable * cfg['sgst_pct'] / 100, 2)
        else:
            taxable = fee_record.amount_paid
            total = taxable
            cgst = sgst = 0
        inv_no = self._next_invoice_number()

        bill_name = (company_bill_name(company) if company is not None
                     else (cfg['org_name'] or 'Guha India'))
        bill_address = (company.address if company is not None and company.address
                        else cfg['org_address'])
        bill_gstin = (company.gstin if company is not None and company.gstin
                      else cfg['org_gstin'])
        bill_phone = (company.phone if company is not None and company.phone
                      else cfg['org_mobile'])
        bill_email = (company.email if company is not None and company.email
                      else cfg['org_email'])

        pdf = FPDF()
        pdf.alias_nb_pages()
        pdf.set_auto_page_break(auto=True, margin=20)
        # Helvetica cannot encode Indian-language names or other Unicode
        # student/company data. DejaVu is bundled with the application and is
        # supported by fpdf2 on Render and locally.
        font_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'static', 'fonts')
        regular_font = os.path.join(font_dir, 'DejaVuSans.ttf')
        bold_font = os.path.join(font_dir, 'DejaVuSans-Bold.ttf')
        if os.path.exists(regular_font) and os.path.exists(bold_font):
            pdf.add_font('DejaVu', '', regular_font)
            pdf.add_font('DejaVu', 'B', bold_font)
            pdf_font = 'DejaVu'
        else:
            pdf_font = 'Helvetica'
        pdf.add_page()

        def text_color(r, g, b):
            pdf.set_text_color(r, g, b)

        def set_font(style='', size=10):
            pdf.set_font(pdf_font, style, size)

        # Header band (light grey)
        pdf.set_fill_color(241, 243, 246)
        pdf.rect(0, 0, 210, 62, 'F')
        pdf.set_draw_color(30, 60, 114)
        pdf.set_line_width(1.0)
        # Keep the accent rule inside the inner page frame so it never
        # intersects either border in the downloaded PDF.
        pdf.line(10, 62, 200, 62)
        pdf.set_line_width(0.2)

        # Logo top-left
        if os.path.exists(LOGO_PATH):
            pdf.image(LOGO_PATH, 14, 12, 34, 34)

        set_font('B', 18)
        text_color(30, 60, 114)
        pdf.set_xy(54, 11)
        pdf.cell(0, 9, bill_name, align='L')
        set_font('B', 12)
        text_color(42, 82, 152)
        pdf.set_xy(54, 21)
        pdf.cell(0, 6, '(Powered By Guha India)', align='L')
        set_font('', 10)
        text_color(45, 45, 45)
        pdf.set_xy(54, 29)
        pdf.multi_cell(64, 5, bill_address, new_x="LMARGIN", new_y="NEXT")
        contact_y = pdf.get_y() + 1
        pdf.set_xy(54, contact_y)
        if has_gst:
            pdf.multi_cell(64, 5, f"GSTIN: {bill_gstin}\nMobile: {bill_phone}\nEmail: {bill_email}", new_x="LMARGIN", new_y="NEXT")
        else:
            pdf.multi_cell(64, 5, f"Mobile: {bill_phone}\nEmail: {bill_email}", new_x="LMARGIN", new_y="NEXT")

        # Right side: title + meta
        set_font('B', 18)
        text_color(30, 60, 114)
        pdf.set_xy(132, 12)
        pdf.cell(66, 10, 'TAX INVOICE' if has_gst else 'FEE RECEIPT', align='R')
        set_font('B', 9.5)
        text_color(40, 40, 40)
        pdf.set_xy(132, 27)
        pdf.cell(66, 6, f"Invoice No: {inv_no}", align='R')
        pdf.set_xy(132, 34)
        pdf.cell(66, 6, f"Date: {fee_record.payment_date.strftime('%d %b %Y')}", align='R')
        pdf.set_xy(132, 41)
        pdf.cell(66, 6, "Place of Supply: Tamil Nadu (33)", align='R')

        pdf.set_y(70)

        # Bill To (left) and Payment & Terms (right)
        set_font('B', 12)
        text_color(30, 60, 114)
        pdf.set_xy(15, 70)
        pdf.cell(0, 8, 'Bill To (Student):', new_x="LMARGIN", new_y="NEXT")
        pdf.set_draw_color(140, 150, 165)
        pdf.line(15, pdf.get_y(), 95, pdf.get_y())
        pdf.ln(2)
        set_font('', 10.5)
        text_color(25, 25, 25)
        pdf.set_x(15)
        pdf.cell(0, 7, student.name or 'N/A', new_x="LMARGIN", new_y="NEXT")
        if student.email:
            pdf.set_x(15); pdf.cell(0, 6, f"Email: {student.email}", new_x="LMARGIN", new_y="NEXT")
        if student.phone:
            pdf.set_x(15); pdf.cell(0, 6, f"Phone: {student.phone}", new_x="LMARGIN", new_y="NEXT")

        set_font('B', 12)
        text_color(30, 60, 114)
        pdf.set_xy(120, 70)
        pdf.cell(0, 8, 'Payment & Terms:', new_x="LMARGIN", new_y="NEXT")
        pdf.line(120, pdf.get_y(), 195, pdf.get_y())
        pdf.ln(2)
        set_font('', 10.5)
        text_color(25, 25, 25)
        pdf.set_x(120); pdf.cell(0, 6, f"Mode: {fee_record.payment_method}", new_x="LMARGIN", new_y="NEXT")
        pdf.set_x(120); pdf.cell(0, 6, "Terms: Due on Receipt", new_x="LMARGIN", new_y="NEXT")
        pdf.set_x(120); pdf.cell(0, 6, f"Place of Supply: {cfg['org_state']} ({cfg['org_state_code']})", new_x="LMARGIN", new_y="NEXT")
        if has_gst:
            pdf.set_x(120); pdf.cell(0, 6, "Reverse Charge: No", new_x="LMARGIN", new_y="NEXT")
        if fee_record.remarks:
            pdf.set_x(120); pdf.cell(0, 6, f"Remarks: {fee_record.remarks}", new_x="LMARGIN", new_y="NEXT")

        pdf.ln(6)

        # Invoice items table
        set_font('B', 12)
        text_color(30, 60, 80)
        pdf.set_x(15)
        pdf.cell(0, 8, 'Fee Details', new_y="NEXT")
        pdf.line(15, pdf.get_y(), 195, pdf.get_y())
        pdf.ln(3)

        if has_gst:
            col_w = [70, 18, 24, 20, 20, 28]
            headers = ['Description', 'HSN/SAC', 'Amount', 'CGST', 'SGST', 'Total']
        else:
            col_w = [82, 30, 32, 36]
            headers = ['Description', 'HSN/SAC', 'Amount', 'Total']

        def table_header():
            set_font('B', 9.5)
            pdf.set_fill_color(10, 30, 46)
            text_color(255, 255, 255)
            pdf.set_x(15)
            for i, h in enumerate(headers):
                pdf.cell(col_w[i], 8, h, border=1, fill=True, align='C')
            pdf.ln()

        def table_row(cols, bold=False, fill=False):
            if fill:
                pdf.set_fill_color(238, 243, 250)
            else:
                pdf.set_fill_color(255, 255, 255)
            text_color(25, 25, 25)
            set_font('B' if bold else '', 9.5)
            pdf.set_x(15)
            for i, c in enumerate(cols):
                pdf.cell(col_w[i], 8, str(c), border=1, fill=True, align='C' if i > 0 else 'L')
            pdf.ln()

        table_header()
        # W1: one installment line, not full course fees. Line items must sum
        # to the totals row (which uses the stored split); listing every
        # course at full price made part-payments self-contradictory.
        desc = self.invoice_item_description(fee_record)
        for row in build_invoice_item_rows(desc, has_gst, cfg['org_hsn'], taxable, cgst, sgst, total):
            table_row(row, fill=True)

        # Totals
        pdf.ln(2)
        if has_gst:
            table_row(['', '', '', '', 'Total', f'Rs. {total:,.2f}'], bold=True, fill=True)
        else:
            table_row(['', '', 'Total', f'Rs. {total:,.2f}'], bold=True, fill=True)

        # Amount in words (simple)
        pdf.ln(5)
        set_font('', 9.5)
        text_color(25, 25, 25)
        import math
        words = self._number_to_words(int(math.floor(total)))
        pdf.set_x(15)
        pdf.cell(180, 6, f"Amount in words: Rupees {words} only.", new_y="NEXT")

        pdf.ln(8)

        # Notes
        set_font('', 9)
        text_color(80, 80, 80)
        pdf.set_x(15)
        pdf.multi_cell(180, 5, f"Note: {BILL_NOTE}", new_y="NEXT")

        # Fixed footer layout: stop auto page-breaking so the signature/footer bands stay put
        pdf.set_auto_page_break(auto=False)

        # Signature & declaration (space above reserved for company seal)
        pdf.set_y(232)
        sig_y = pdf.get_y()
        pdf.set_draw_color(90, 90, 90)
        pdf.line(130, sig_y, 195, sig_y)
        pdf.set_xy(130, sig_y - 12)
        set_font('', 8.5)
        text_color(70, 70, 70)
        pdf.cell(65, 5, "(Seal & Signature)", align='R')
        pdf.set_xy(130, sig_y + 2)
        set_font('B', 9)
        text_color(25, 25, 25)
        pdf.cell(65, 6, "Authorised Signatory", align='R')

        # Footer band with company details
        pdf.set_fill_color(241, 243, 246)
        pdf.rect(0, 258, 210, 31, 'F')
        pdf.set_draw_color(30, 60, 114)
        pdf.set_line_width(1.0)
        # Separator sits on the footer band's top edge, above the academy name.
        pdf.line(10, 258, 200, 258)
        pdf.set_line_width(0.2)
        set_font('B', 10)
        text_color(30, 60, 114)
        pdf.set_xy(10, 262)
        pdf.cell(190, 6, bill_name, align='C')
        set_font('', 8.5)
        text_color(45, 45, 45)
        pdf.set_xy(10, 268)
        pdf.cell(190, 5, bill_address, align='C')
        pdf.set_xy(10, 274)
        pdf.cell(190, 4, f"GSTIN: {bill_gstin}  |  Mobile: {bill_phone}", align='C')
        pdf.set_xy(10, 278)
        pdf.cell(190, 4, f"Email: {bill_email}", align='C')
        pdf.set_xy(10, 283)
        pdf.set_font(pdf_font, '', 7.5)
        pdf.cell(190, 4, f"Generated: {datetime.now().strftime('%d %b %Y %I:%M %p')}", align='C')

        # Page border (drawn last so it frames header/footer bands)
        pdf.set_draw_color(30, 60, 114)
        pdf.set_line_width(0.7)
        pdf.rect(8, 8, 194, 281, 'D')
        pdf.set_draw_color(170, 180, 195)
        pdf.set_line_width(0.3)
        pdf.rect(10, 10, 190, 277, 'D')

        buf = BytesIO()
        pdf.output(buf)
        buf.seek(0)
        return buf, inv_no

    def _number_to_words(self, n):
        ones = ['', 'One', 'Two', 'Three', 'Four', 'Five', 'Six', 'Seven', 'Eight', 'Nine',
                'Ten', 'Eleven', 'Twelve', 'Thirteen', 'Fourteen', 'Fifteen', 'Sixteen',
                'Seventeen', 'Eighteen', 'Nineteen']
        tens = ['', '', 'Twenty', 'Thirty', 'Forty', 'Fifty', 'Sixty', 'Seventy', 'Eighty', 'Ninety']
        if n == 0:
            return 'Zero'
        def convert(num):
            if num < 20:
                return ones[num]
            elif num < 100:
                return tens[num // 10] + (' ' + ones[num % 10] if num % 10 else '')
            elif num < 1000:
                return ones[num // 100] + ' Hundred' + (' ' + convert(num % 100) if num % 100 else '')
            elif num < 100000:
                return convert(num // 1000) + ' Thousand' + (' ' + convert(num % 1000) if num % 1000 else '')
            elif num < 10000000:
                return convert(num // 100000) + ' Lakh' + (' ' + convert(num % 100000) if num % 100000 else '')
            else:
                return convert(num // 10000000) + ' Crore' + (' ' + convert(num % 10000000) if num % 10000000 else '')
        return convert(n)

    def generate_tally_xml(self, fee_records, filename='tally_export.xml'):
        cfg = self._get_settings()
        from xml.etree.ElementTree import Element, SubElement, tostring
        from xml.dom import minidom

        envelope = Element('ENVELOPE')
        header = SubElement(envelope, 'HEADER')
        SubElement(header, 'TALLYREQUEST').text = 'Import Data'
        body = SubElement(envelope, 'BODY')
        import_data = SubElement(body, 'IMPORTDATA')
        tally_msg = SubElement(import_data, 'TALLYMESSAGE')

        SubElement(tally_msg, 'VCHTYPE').text = 'Receipt'

        for fr in fee_records:
            student = fr.student
            voucher = SubElement(tally_msg, 'VOUCHER', {
                'VCHTYPE': 'Receipt',
                'ACTION': 'Create',
            })
            SubElement(voucher, 'DATE').text = fr.payment_date.strftime('%Y%m%d')
            SubElement(voucher, 'NARRATION').text = f"Fee received from {student.name} - {fr.remarks or 'Course Fee'}"
            SubElement(voucher, 'VOUCHERTYPENAME').text = 'Receipt'
            SubElement(voucher, 'PARTYLEDGERNAME').text = f'{student.name} - Fee'
            SubElement(voucher, 'EFFECTIVEDATE').text = fr.payment_date.strftime('%Y%m%d')

            # Debit: Bank/Cash
            all_ledgers = SubElement(voucher, 'ALLLEDGERENTRIES.LIST')
            SubElement(all_ledgers, 'LEDGERNAME').text = TALLY_ACCOUNT_FOR_METHOD.get(classify_method(fr.payment_method), 'Bank')
            SubElement(all_ledgers, 'ISDEEMEDPOSITIVE').text = 'Yes'
            SubElement(all_ledgers, 'AMOUNT').text = f'{fr.amount_paid:,.2f}'

            # Credit: Student Fee ledger
            all_ledgers2 = SubElement(voucher, 'ALLLEDGERENTRIES.LIST')
            SubElement(all_ledgers2, 'LEDGERNAME').text = f'{student.name} - Fee'
            SubElement(all_ledgers2, 'ISDEEMEDPOSITIVE').text = 'No'
            SubElement(all_ledgers2, 'AMOUNT').text = f'-{fr.amount_paid:,.2f}'

        xml_str = minidom.parseString(tostring(envelope, encoding='unicode')).toprettyxml(indent='  ')
        return xml_str.encode('utf-8')

    def generate_zoho_csv(self, fee_records):
        import csv
        import io
        buf = io.StringIO()
        writer = csv.writer(buf)
        writer.writerow(['Date', 'Student Name', 'Student Email', 'Description', 'Amount', 'Payment Method', 'Invoice No'])

        for fr in fee_records:
            student = fr.student
            # Generate a simple invoice ref
            inv_ref = f"INV-{fr.payment_date.strftime('%Y%m')}-{fr.id}"
            writer.writerow([
                fr.payment_date.strftime('%Y-%m-%d'),
                student.name,
                student.email,
                fr.remarks or 'Course Fee Payment',
                f'{fr.amount_paid:.2f}',
                fr.payment_method,
                inv_ref,
            ])
        return buf.getvalue().encode('utf-8')
