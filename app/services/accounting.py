from datetime import datetime, date
from io import BytesIO
from fpdf import FPDF
from app.extensions import db


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
            'org_name': val('ORG_NAME') or 'Guha Academy',
            'org_address': val('ORG_ADDRESS') or '123, Institute Road, City',
            'org_gstin': val('ORG_GSTIN') or '',
            'org_hsn': val('ORG_HSN') or '999293',
            'org_state': val('ORG_STATE') or 'State',
            'org_state_code': val('ORG_STATE_CODE') or '99',
            'cgst_pct': float(val('CGST_PCT') or '9'),
            'sgst_pct': float(val('SGST_PCT') or '9'),
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

    def generate_invoice_pdf(self, fee_record):
        cfg = self._get_settings()
        student = fee_record.student
        courses = list(student.courses)
        has_gst = any(c.gst_applicable for c in courses)
        total_fee = sum(c.fees for c in courses)

        if has_gst:
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

        pdf = FPDF()
        pdf.alias_nb_pages()
        pdf.set_auto_page_break(auto=True, margin=20)
        pdf.add_page()

        def text_color(r, g, b):
            pdf.set_text_color(r, g, b)

        def set_font(style='', size=10):
            pdf.set_font('Helvetica', style, size)

        # Header block
        pdf.set_fill_color(10, 30, 46)
        pdf.rect(0, 0, 210, 45, 'F')
        set_font('B', 20)
        text_color(0, 212, 255)
        pdf.set_xy(15, 8)
        pdf.cell(0, 10, cfg['org_name'], align='L')
        set_font('', 8)
        text_color(200, 200, 200)
        pdf.set_xy(15, 20)
        pdf.cell(0, 5, cfg['org_address'], align='L')
        if cfg['org_gstin']:
            pdf.set_xy(15, 27)
            pdf.cell(0, 5, f"GSTIN: {cfg['org_gstin']}", align='L')
        pdf.set_xy(15, 36)
        pdf.cell(0, 5, f"State: {cfg['org_state']}  Code: {cfg['org_state_code']}", align='L')

        set_font('B', 16)
        text_color(255, 255, 255)
        pdf.set_xy(130, 12)
        pdf.cell(65, 10, 'TAX INVOICE' if has_gst else 'FEE RECEIPT', align='R')
        set_font('', 9)
        text_color(200, 200, 200)
        pdf.set_xy(130, 24)
        pdf.cell(65, 5, f"Invoice No: {inv_no}", align='R')
        pdf.set_xy(130, 31)
        pdf.cell(65, 5, f"Date: {fee_record.payment_date.strftime('%d %b %Y')}", align='R')

        pdf.ln(50)

        # Bill To
        set_font('B', 10)
        text_color(30, 60, 80)
        pdf.cell(0, 7, 'Bill To:', new_x="LMARGIN", new_y="NEXT")
        pdf.set_draw_color(200, 200, 200)
        pdf.line(15, pdf.get_y(), 195, pdf.get_y())
        pdf.ln(3)
        set_font('', 9)
        text_color(60, 60, 60)
        for label, val in [('Name', student.name), ('Email', student.email), ('Phone', student.phone)]:
            pdf.cell(30, 6, label)
            pdf.cell(0, 6, val, new_x="LMARGIN", new_y="NEXT")

        pdf.ln(5)

        # Invoice items table
        set_font('B', 10)
        text_color(30, 60, 80)
        pdf.cell(0, 7, 'Fee Details', new_x="LMARGIN", new_y="NEXT")
        pdf.line(15, pdf.get_y(), 195, pdf.get_y())
        pdf.ln(3)

        if has_gst:
            col_w = [70, 25, 25, 25, 25, 25]
            headers = ['Description', 'HSN/SAC', 'Amount', 'CGST', 'SGST', 'Total']
        else:
            col_w = [90, 30, 30, 40]
            headers = ['Description', 'HSN/SAC', 'Amount', 'Total']

        def table_header():
            set_font('B', 8)
            pdf.set_fill_color(10, 30, 46)
            text_color(255, 255, 255)
            for i, h in enumerate(headers):
                pdf.cell(col_w[i], 7, h, border=1, fill=True, align='C')
            pdf.ln()

        def table_row(cols, bold=False, fill=False):
            if fill:
                pdf.set_fill_color(240, 245, 250)
            else:
                pdf.set_fill_color(255, 255, 255)
            text_color(30, 30, 30)
            set_font('B' if bold else '', 8)
            for i, c in enumerate(cols):
                pdf.cell(col_w[i], 6, str(c), border=1, fill=True, align='C' if i > 0 else 'L')
            pdf.ln()

        table_header()
        if has_gst:
            for course in courses:
                cgst_c = round(course.fees * cfg['cgst_pct'] / 100, 2)
                sgst_c = round(course.fees * cfg['sgst_pct'] / 100, 2)
                total_c = course.fees + cgst_c + sgst_c
                table_row([course.name, cfg['org_hsn'], f'Rs. {course.fees:,.2f}', f'Rs. {cgst_c:,.2f}', f'Rs. {sgst_c:,.2f}', f'Rs. {total_c:,.2f}'], fill=True)
        else:
            course_names = ', '.join(c.name for c in courses) if courses else 'Course Fee'
            table_row([course_names, cfg['org_hsn'], f'Rs. {taxable:,.2f}', f'Rs. {total:,.2f}'], fill=True)

        # Totals
        pdf.ln(2)
        if has_gst:
            table_row(['', '', '', '', 'Total', f'Rs. {total:,.2f}'], bold=True, fill=True)
        else:
            table_row(['', '', 'Total', f'Rs. {total:,.2f}'], bold=True, fill=True)

        # Amount in words (simple)
        pdf.ln(5)
        set_font('', 8)
        text_color(100, 100, 100)
        import math
        words = self._number_to_words(int(math.floor(total)))
        pdf.cell(0, 5, f"Amount in words: Rupees {words} only.", new_x="LMARGIN", new_y="NEXT")

        pdf.ln(10)

        # Signature & declaration
        pdf.line(130, pdf.get_y(), 195, pdf.get_y())
        pdf.set_xy(130, pdf.get_y() + 2)
        set_font('', 8)
        text_color(100, 100, 100)
        pdf.cell(65, 5, f"Authorised Signatory - {cfg['org_name']}", align='R')

        pdf.set_y(pdf.get_y() + 8)
        set_font('', 7)
        text_color(150, 150, 150)
        pdf.cell(0, 4, "This is a computer-generated invoice.", align='C')
        pdf.cell(0, 4, f"Generated: {datetime.now().strftime('%d %b %Y %I:%M %p')}", align='C')

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
            SubElement(all_ledgers, 'LEDGERNAME').text = fr.payment_method if fr.payment_method in ('Cash', 'Bank') else 'Bank'
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
