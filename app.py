import streamlit as st
import fitz  # PyMuPDF
import re
import io
import zipfile
import pandas as pd
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import A4
from collections import defaultdict

# ================= Config สี (ปรับให้สว่างพิเศษเพื่อการปริ้นขาวดำ) =================
HIGHLIGHT_STUDENT = (1.0, 1.0, 0.85)  # เหลืองจางมาก
HIGHLIGHT_TIME = (0.93, 1.0, 0.93)     # เขียวจางมาก
HIGHLIGHT_ROOM = (0.93, 0.96, 1.0)     # ฟ้าจางมาก
STRIKE_COLOR = (1.0, 0.7, 0.7)        # แดงอ่อน (สำหรับขีดฆ่าคนขาด)

st.set_page_config(page_title="BLC Mega Agenda Tool", page_icon="🚀", layout="wide")

# ================= Logic ดึงข้อมูลนักเรียน =================

def parse_students_robust(text):
    students = []
    text = re.sub(r'(?:Group\s+|Private\s+)?Lesson\s*-\s*', '', text, flags=re.IGNORECASE)
    STOP_KEYWORDS = ['Cambridge Classroom', 'Oxford Classroom', 'Canterbury Classroom', 'Warwick Classroom', 'Teacher Classroom', 'Teacher Room', 'EYFS Classroom', '1-to-1 Room', '2-to-1 Room', 'Ground Floor', '1to-1 Room', '- Online']
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

# ================= ฟังก์ชันสร้างแบบฟอร์มแบบใหม่ (ประหยัดพื้นที่) =================

def draw_eval_block(can, data, start_y):
    """วาดหนึ่งคลาส (Block) และคืนค่าตำแหน่ง Y สุดท้ายที่วาดเสร็จ"""
    width, height = A4
    y = start_y
    
    # เช็คพื้นที่คงเหลือ
    estimated_height = 120 + (len(data.get('Students', [])) * 25)
    if y - estimated_height < 50:
        can.showPage()
        y = height - 50
        draw_legend_box(can, height)

    # --- หัวข้อคลาส ---
    is_math = data.get('is_math', False)
    title_suffix = "Math" if is_math else "English"
    spelling_header = "99 Club" if is_math else "Spelling"
    
    can.setFont("Helvetica-Bold", 14)
    can.drawString(50, y, f"Student Evaluation Form - {title_suffix}")
    y -= 25
    
    can.setFont("Helvetica", 10)
    can.drawString(50, y, f"Date: {data.get('Date', '')}  |  Time: {data.get('Time', '')}")
    y -= 15
    can.drawString(50, y, f"Teacher: {data.get('Teacher', '')}  |  Room: {data.get('Classroom', '')}")
    y -= 15
    can.drawString(50, y, f"WALT: {data.get('WALT', '')}")
    y -= 25

    # --- ตารางนักเรียน ---
    headers = ["Name", "Effort", spelling_header, "Teacher Assessment"]
    cols = [200, 80, 80, 130]
    row_h = 25
    
    can.setFont("Helvetica-Bold", 9)
    x = 50
    for i, h in enumerate(headers):
        can.rect(x, y - row_h, cols[i], row_h)
        can.drawString(x + 5, y - row_h + 7, h)
        x += cols[i]
    y -= row_h

    can.setFont("Helvetica", 9)
    student_list = [s for s in data.get('Students', []) if not s['is_absent']]
    
    if not student_list:
        x = 50
        for w in cols:
            can.rect(x, y - row_h, w, row_h)
            x += w
        can.drawString(55, y - row_h + 7, "(No students present)")
        y -= row_h
    else:
        for s in student_list:
            x = 50
            for i, w in enumerate(cols):
                can.rect(x, y - row_h, w, row_h)
                if i == 0: can.drawString(x + 5, y - row_h + 7, s['nickname'])
                elif i == 1: can.drawCentredString(x + w/2, y - row_h + 7, "/ 5")
                elif i == 3: can.drawCentredString(x + w/2, y - row_h + 7, "R    Y    G")
                x += w
            y -= row_h

    return y - 30

def draw_legend_box(can, height):
    can.setFont("Helvetica", 8)
    box_x, box_y, box_w, box_h = 440, height - 85, 110, 60
    can.rect(box_x, box_y, box_w, box_h)
    legend_items = ["1 - Unsatisfactory", "2 - Could do better", "3 - Satisfactory", "4 - Gold", "5 - Outstanding"]
    text_y = box_y + box_h - 10
    for item in legend_items:
        can.drawString(box_x + 5, text_y, item)
        text_y -= 10

def create_combined_evals_pdf(all_blocks):
    packet = io.BytesIO()
    can = canvas.Canvas(packet, pagesize=A4)
    width, height = A4
    
    teacher_groups = defaultdict(list)
    for b in all_blocks:
        teacher_groups[b['Teacher']].append(b)
    
    for teacher, blocks in teacher_groups.items():
        y_cursor = height - 50
        draw_legend_box(can, height)
        for block_data in blocks:
            y_cursor = draw_eval_block(can, block_data, y_cursor)
        can.showPage()
        
    can.save()
    packet.seek(0)
    return packet

# ================= ฟังก์ชันประมวลผล PDF =================

def process_everything(file_bytes):
    doc = fitz.open(stream=file_bytes, filetype="pdf")
    all_blocks_data = []
    ROOM_INDICATORS = ["Cambridge Classroom", "Oxford Classroom", "Canterbury Classroom", "Warwick Classroom", "Teacher Classroom", "Teacher Room", "EYFS Classroom", "Ground Floor", "1-to-1 Room", "2-to-1 Room", "1to-1 Room", "Online Lesson"]

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
            
            # --- ระบบใหม่: ตรวจจับประเภทคลาสและห้องเรียน ---
            lesson_type = ""
            text_lower = block_text.lower()
            
            if any(kw in text_lower for kw in ["one to one", "1 to 1", "1-to-1", "1to-1", "1-1", "private"]):
                lesson_type = "1 to 1 "
            elif any(kw in text_lower for kw in ["two to one", "2 to 1", "2-to-1", "2-1"]):
                lesson_type = "2 to 1 "
                
            detected_room = "Unknown Room"
            for r in ROOM_INDICATORS:
                if r.lower() in text_lower:
                    detected_room = r
                    break
            
            # รวมร่าง (ยกเว้น Cambridge และ EYFS ที่ห้ามใส่ 1to1/2to1)
            is_restricted = any(name in detected_room for name in ["Cambridge", "EYFS"])
            already_has_info = "1-to-1" in detected_room or "2-to-1" in detected_room
            
            if is_restricted or already_has_info:
                fb["Classroom"] = detected_room
            else:
                fb["Classroom"] = f"{lesson_type}{detected_room}".strip()

            # --- เช็ควิชา Math ---
            is_math_block = "math" in text_lower
            fb["is_math"] = is_math_block

            # --- ไฮไลท์สีใน PDF (กู้คืนกลับมา) ---
            # ไฮไลท์ห้องเรียน
            if detected_room != "Unknown Room":
                for inst in page.search_for(detected_room):
                    annot = page.add_highlight_annot(inst)
                    if annot:
                        annot.set_colors(stroke=HIGHLIGHT_ROOM)
                        annot.update()

            # ไฮไลท์นักเรียน
            for student in fb["Students"]:
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

            # ดึงข้อมูล WALT (ดึงเฉพาะจากบรรทัดที่มีชื่อห้องเรียนเพื่อความแม่นยำ)
            for line in fb["raw"]:
                if any(r in line for r in ROOM_INDICATORS) and " - " in line:
                    walt_text = line.split(" - ", 1)[1].strip()
                    fb["WALT"] = walt_text
                    # เช็ควิชา Math จาก WALT อีกรอบเพื่อความชัวร์
                    if "math" in walt_text.lower():
                        fb["is_math"] = True
                    break # เจอแล้วหยุดเลย
            
            all_blocks_data.append(fb)
    
    out_pdf = io.BytesIO()
    doc.save(out_pdf)
    doc.close()
    out_pdf.seek(0)
    return out_pdf, all_blocks_data

# ================= UI =================

def main():
    st.title("🚀 BLC Mega Agenda Tool")
    st.write("เวอร์ชันอัปเกรด: ตรวจจับคลาส 1to1 / 2to1 และห้องเรียนแบบละเอียด")

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
