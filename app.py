import streamlit as st
import fitz  # PyMuPDF
import re
import io
import zipfile
import pandas as pd
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import A4

# ================= Config สี (ปรับให้สว่างพิเศษเพื่อการปริ้นขาวดำ) =================
HIGHLIGHT_STUDENT = (1.0, 1.0, 0.85)  # เหลืองจางมาก
HIGHLIGHT_TIME = (0.93, 1.0, 0.93)     # เขียวจางมาก
HIGHLIGHT_ROOM = (0.93, 0.96, 1.0)     # ฟ้าจางมาก
STRIKE_COLOR = (1.0, 0.7, 0.7)        # แดงอ่อน (สำหรับขีดฆ่าคนขาด)

st.set_page_config(page_title="BLC Mega Agenda Tool", page_icon="🚀", layout="wide")

# ================= Logic ดึงข้อมูลนักเรียน =================

def parse_students_robust(text):
    students = []
    text = re.sub(r'(?:Group|Private)\s+Lesson\s*-\s*', '', text, flags=re.IGNORECASE)
    STOP_KEYWORDS = ['Cambridge Classroom', 'Oxford Classroom', 'Teacher Classroom', 'EYFS Classroom', '1-to-1 Room', '2-to-1 Room', 'Ground Floor', '1to-1 Room', '- Online']
    for kw in STOP_KEYWORDS:
        idx = text.find(kw)
        if idx != -1: text = text[:idx]
    
    segments = text.replace('\n', ' ').split(';')
    for segment in segments:
        segment = segment.strip()
        if not segment or segment in ['-', '–']: continue
        is_absent = 'Absent' in segment or 'Notice Given' in segment
        clean_seg = re.sub(r'\s*\([^)]*\)', '', segment).strip()
        if not clean_seg: continue
        parts = clean_seg.split(' - ')
        nickname = parts[0].strip().split(' ')[0]
        if nickname and len(nickname) > 1 and not nickname.isdigit():
            students.append({'nickname': nickname, 'original': segment, 'is_absent': is_absent})
    return students

# ================= ฟังก์ชันสร้างแบบฟอร์มแบบรวมไฟล์ (Multi-page) =================

def draw_single_eval_page(can, data):
    """วาดหน้าใบประเมิน 1 หน้า"""
    width, height = A4
    can.setFont("Helvetica-Bold", 16)
    can.drawString(50, height - 50, "Student Evaluation Form - English")
    can.setFont("Helvetica", 11)
    can.drawString(50, height - 80, f"Date:  {data.get('Date', '')}")
    can.drawString(50, height - 100, f"WALT:  {data.get('WALT', '')}")
    can.drawString(50, height - 120, f"Teacher Name:  {data.get('Teacher', '')}")
    can.drawString(50, height - 140, f"Classroom:  {data.get('Classroom', '')}")
    can.drawString(50, height - 160, f"Time:  {data.get('Time', '')}")

    table_top, row_h = height - 200, 25
    cols = [200, 80, 80, 130]
    
    # --- เช็คว่าเป็นวิชา Math หรือไม่ ---
    is_math = data.get('is_math', False)
    spelling_header = "99 Club" if is_math else "Spelling"
    headers = ["Name", "Effort", spelling_header, "Teacher Assessment"]
    
    x = 50
    can.setFont("Helvetica-Bold", 10)
    for i, h in enumerate(headers):
        can.rect(x, table_top, cols[i], row_h)
        can.drawString(x + 5, table_top + 7, h)
        x += cols[i]

    can.setFont("Helvetica", 10)
    student_list = [s['nickname'] for s in data.get('Students', []) if not s['is_absent']]
    y_current = table_top
    for row in range(10):
        y_current = table_top - (row + 1) * row_h
        x = 50
        name = student_list[row] if row < len(student_list) else ""
        for i, w in enumerate(cols):
            can.rect(x, y_current, w, row_h)
            if i == 0: can.drawString(x + 5, y_current + 7, name)
            elif i == 1: can.drawCentredString(x + w/2, y_current + 7, "/ 5")
            elif i == 3: can.drawCentredString(x + w/2, y_current + 7, "R    Y    G")
            x += w
    
    footer_y = y_current - 40
    for item in ["Phonics:", "Grammar:", "Speaking and Listening:", "RWI/Fresh Start Book:", "Main Learning:"]:
        can.drawString(50, footer_y, item)
        can.line(50, footer_y - 2, 540, footer_y - 2)
        footer_y -= 30
    can.showPage()

def create_combined_evals_pdf(all_blocks):
    """สร้าง PDF รวมทุกใบประเมินไว้ในไฟล์เดียว"""
    packet = io.BytesIO()
    can = canvas.Canvas(packet, pagesize=A4)
    for block_data in all_blocks:
        draw_single_eval_page(can, block_data)
    can.save()
    packet.seek(0)
    return packet

# ================= ฟังก์ชันประมวลผล PDF =================

def process_everything(file_bytes):
    doc = fitz.open(stream=file_bytes, filetype="pdf")
    all_blocks_data = []
    ROOM_INDICATORS = ["Cambridge Classroom", "Oxford Classroom", "Teacher Classroom", "EYFS Classroom", "1-to-1 Room", "2-to-1 Room", "Ground Floor", "1to-1 Room"]

    for page in doc:
        full_text = page.get_text()
        lines = [l.strip() for l in full_text.split('\n') if l.strip()]
        
        teacher, agenda_date = "Unknown", "Unknown"
        for i, line in enumerate(lines):
            if re.search(r'(?:Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday),', line):
                agenda_date = line
                if i > 0: teacher = lines[i-1]
                break

        current_block = None
        time_pattern = re.compile(r'^\d{1,2}:\d{2}\s+(?:AM|PM)\s*-\s*\d{1,2}:\d{2}\s+(?:AM|PM)')
        
        page_blocks = []
        for line in lines:
            if time_pattern.match(line):
                if current_block: page_blocks.append(current_block)
                current_block = {"Date": agenda_date, "Teacher": teacher, "Time": line, "Classroom": "Unknown", "WALT": "Unknown", "Students": [], "raw": [], "is_math": False}
                for inst in page.search_for(line):
                    annot = page.add_highlight_annot(inst)
                    if annot: 
                        annot.set_colors(stroke=HIGHLIGHT_TIME)
                        annot.update()
            elif current_block:
                current_block["raw"].append(line)
        if current_block: page_blocks.append(current_block)

        for fb in page_blocks:
            block_text = "\n".join(fb["raw"])
            fb["Students"] = parse_students_robust(block_text)
            
            # --- เช็ควิชา Math ---
            if "math" in block_text.lower():
                fb["is_math"] = True

            for student in fb["Students"]:
                # ไฮไลท์นักเรียน
                for inst in page.search_for(student['nickname']):
                    if student['is_absent']:
                        annot = page.add_strikeout_annot(inst)
                        if annot: 
                            annot.set_colors(stroke=STRIKE_COLOR)
                            annot.update()
                    else:
                        annot = page.add_highlight_annot(inst)
                        if annot: 
                            annot.set_colors(stroke=HIGHLIGHT_STUDENT)
                            annot.update()

            for line in fb["raw"]:
                room = next((r for r in ROOM_INDICATORS if r in line), None)
                if room:
                    fb["Classroom"] = room
                    if " - " in line: 
                        walt_text = line.split(" - ", 1)[1].strip()
                        fb["WALT"] = walt_text
                        if "math" in walt_text.lower():
                            fb["is_math"] = True
                    
                    for inst in page.search_for(room):
                        annot = page.add_highlight_annot(inst)
                        if annot: 
                            annot.set_colors(stroke=HIGHLIGHT_ROOM)
                            annot.update()
            all_blocks_data.append(fb)
    
    out_pdf = io.BytesIO()
    doc.save(out_pdf)
    doc.close()
    out_pdf.seek(0)
    return out_pdf, all_blocks_data

# ================= UI =================

def main():
    st.title("🚀 BLC Mega Agenda Tool")
    st.write("รองรับการเปลี่ยน Spelling เป็น 99 Club สำหรับวิชา Math อัตโนมัติ")

    uploaded_files = st.file_uploader("Upload Agenda PDF", type="pdf", accept_multiple_files=True)

    if uploaded_files:
        zip_buffer = io.BytesIO()
        all_recs_summary = []
        all_blocks_for_combined = []

        with st.spinner('กำลังประมวลผล...'):
            with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zip_file:
                for uploaded_file in uploaded_files:
                    try:
                        checked_pdf, block_data = process_everything(uploaded_file.read())
                        zip_file.writestr(f"Checked_{uploaded_file.name}", checked_pdf.getvalue())
                        all_blocks_for_combined.extend(block_data)
                        all_recs_summary.extend(block_data)
                    except Exception as e:
                        st.error(f"เกิดข้อผิดพลาดกับไฟล์ {uploaded_file.name}: {e}")

                if all_blocks_for_combined:
                    combined_evals_pdf = create_combined_evals_pdf(all_blocks_for_combined)
                    zip_file.writestr("All_Evaluations.pdf", combined_evals_pdf.getvalue())

            zip_buffer.seek(0)
            if all_recs_summary:
                st.success(f"ประมวลผลสำเร็จ! รวมทั้งหมด {len(all_recs_summary)} คาบเรียน")
                df = pd.DataFrame(all_recs_summary).drop(columns=['raw'])
                st.dataframe(df)
                st.download_button("📥 Download All Files (ZIP)", zip_buffer, "BLC_Pack.zip", "application/zip")
                st.balloons()

if __name__ == '__main__':
    main()
