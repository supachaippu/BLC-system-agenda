import streamlit as st
import fitz  # PyMuPDF
import re
import io
import zipfile

# ================= Config หน้าตาโปรแกรม =================
st.set_page_config(
    page_title="BLC Agenda Checker v7.2",
    page_icon="📋",
    layout="centered"
)

# Custom CSS เพื่อความสวยงาม (Premium Look)
st.markdown("""
    <style>
    .main {
        background-color: #f8f9fa;
    }
    .stButton>button {
        width: 100%;
        border-radius: 10px;
        height: 3em;
        background-color: #0d6efd;
        color: white;
        font-weight: bold;
    }
    .upload-text {
        text-align: center;
        color: #6c757d;
    }
    </style>
    """, unsafe_allow_html=True)

# ================= Config สี =================
HIGHLIGHT_STUDENT = (1, 1, 0)
HIGHLIGHT_TIME = (0.8, 1, 0.8)
HIGHLIGHT_ROOM = (0.7, 0.9, 1)
STRIKE_COLOR = (1, 0, 0)

# ================= Logic การประมวลผล =================

def parse_agenda_blocks(text):
    blocks = []
    lines = text.split('\n')
    current_block = []
    time_pattern = re.compile(r'^\d{1,2}:\d{2}\s+(AM|PM)\s*-\s*\d{1,2}:\d{2}\s+(AM|PM)')
    for line in lines:
        line = line.strip()
        if not line: continue
        if time_pattern.match(line):
            if current_block: blocks.append('\n'.join(current_block))
            current_block = [line]
        else:
            if any(word in line for word in ['AGENDA', 'British Learning Centre', 'Saturday', 'Sunday', 'Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday']): continue
            if re.match(r'^\d{1,2}/\d{1,2}/\d{4}$', line): continue
            if current_block: current_block.append(line)
    if current_block: blocks.append('\n'.join(current_block))
    return blocks

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
        nickname = clean_seg.split()[0] if clean_seg.split() else None
        full_name = clean_seg
        if ' - ' in clean_seg:
            parts = clean_seg.split(' - ', 1)
            nickname = parts[0].strip()
            full_name = parts[1].strip() if len(parts) > 1 else None
        if nickname and len(nickname) > 1 and not nickname.isdigit():
            students.append({'nickname': nickname, 'full_name': full_name, 'original': segment, 'is_absent': is_absent})
    return students

def extract_students_greedy(block_text):
    lines = block_text.split('\n')
    if not lines: return {'time': None, 'students': []}
    time_str = lines[0]
    all_students = []
    ROOM_INDICATORS = ['Cambridge Classroom', 'Oxford Classroom', 'Teacher Classroom', 'EYFS Classroom', '1-to-1 Room', '2-to-1 Room', 'Ground Floor', '1to-1 Room', 'Room']
    buffer_text = ""
    for line in lines[1:]:
        line = line.strip()
        if not line: continue
        is_room = any(indicator in line for indicator in ROOM_INDICATORS)
        if is_room:
            if buffer_text:
                all_students.extend(parse_students_robust(buffer_text))
                buffer_text = ""
        else:
            if not line.startswith(('KS', 'UKS', 'LKS', 'Year', 'EE', 'Early', 'Reception', 'Phonics')):
                buffer_text += " " + line
    if buffer_text: all_students.extend(parse_students_robust(buffer_text))
    return {'time': time_str, 'students': all_students}

def mark_exact_word(page, text, color, is_absent=False):
    if not text: return 0
    count = 0
    words = page.get_text("words")
    target_clean = re.sub(r'[^\w]', '', text).lower()
    for w in words:
        word_text = w[4]
        word_clean = re.sub(r'[^\w]', '', word_text).lower()
        if word_clean == target_clean:
            rect = fitz.Rect(w[0], w[1], w[2], w[3])
            annot = page.add_strikeout_annot(rect) if is_absent else page.add_highlight_annot(rect)
            annot.set_colors(stroke=color)
            annot.update()
            count += 1
    return count

def find_and_mark_generic(page, text, color, is_absent=False):
    if not text: return 0
    count = 0
    instances = page.search_for(text)
    for inst in instances:
        annot = page.add_strikeout_annot(inst) if is_absent else page.add_highlight_annot(inst)
        annot.set_colors(stroke=color)
        annot.update()
        count += 1
    return count

def mark_structure(page):
    count = 0
    CLASSROOM_TARGETS = ["Cambridge Classroom", "Oxford Classroom", "Teacher Classroom", "EYFS Classroom", "1-to-1 Room", "2-to-1 Room", "Ground Floor", "1to-1 Room"]
    for room in CLASSROOM_TARGETS: count += find_and_mark_generic(page, room, HIGHLIGHT_ROOM)
    return count

def process_single_pdf_bytes(file_bytes):
    doc = fitz.open(stream=file_bytes, filetype="pdf")
    for page in doc:
        full_text = page.get_text()
        blocks = parse_agenda_blocks(full_text)
        mark_structure(page)
        for block in blocks:
            data = extract_students_greedy(block)
            if data['time']:
                time_match = re.match(r'^\d{1,2}:\d{2}\s+(?:AM|PM)\s*-\s*\d{1,2}:\d{2}\s+(?:AM|PM)', data['time'])
                if time_match: find_and_mark_generic(page, time_match.group(0), HIGHLIGHT_TIME)
            for student in data['students']:
                if student['is_absent']:
                    c = find_and_mark_generic(page, student['original'], STRIKE_COLOR, is_absent=True)
                    if c == 0:
                        if ' - ' in student['original']:
                            for part in student['original'].split(' - '):
                                if part.strip(): find_and_mark_generic(page, part.strip(), STRIKE_COLOR, is_absent=True)
                        if ' ' not in student['nickname']:
                            mark_exact_word(page, student['nickname'], STRIKE_COLOR, is_absent=True)
                        else:
                            find_and_mark_generic(page, student['nickname'], STRIKE_COLOR, is_absent=True)
                        if student['full_name']: find_and_mark_generic(page, student['full_name'], STRIKE_COLOR, is_absent=True)
                        for p in re.findall(r'\([^)]+\)', student['original']): find_and_mark_generic(page, p, STRIKE_COLOR, is_absent=True)
                else:
                    if ' ' not in student['nickname']:
                        mark_exact_word(page, student['nickname'], HIGHLIGHT_STUDENT)
                    else:
                        find_and_mark_generic(page, student['nickname'], HIGHLIGHT_STUDENT)
    
    output_buffer = io.BytesIO()
    doc.save(output_buffer)
    doc.close()
    output_buffer.seek(0)
    return output_buffer

# ================= Streamlit UI =================

def main():
    st.markdown("<h2 style='text-align: center; color: #0d6efd;'>📋 BLC Agenda Checker</h2>", unsafe_allow_html=True)
    st.markdown("<p style='text-align: center; color: #6c757d;'>Version 7.2 (Isabella Fix)</p>", unsafe_allow_html=True)
    st.divider()

    uploaded_files = st.file_uploader(
        "Upload PDF Agendas", 
        type="pdf", 
        accept_multiple_files=True,
        help="คุณสามารถเลือกไฟล์ PDF ได้ครั้งละหลายไฟล์"
    )

    if uploaded_files:
        st.info(f"เลือกไฟล์ทั้งหมด {len(uploaded_files)} ไฟล์")
        
        if st.button("🚀 Process and Download"):
            zip_buffer = io.BytesIO()
            
            with st.spinner('กำลังประมวลผลไฟล์... กรุณารอสักครู่'):
                with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zip_file:
                    for uploaded_file in uploaded_files:
                        file_bytes = uploaded_file.read()
                        processed_io = process_single_pdf_bytes(file_bytes)
                        zip_file.writestr(f"Checked_{uploaded_file.name}", processed_io.getvalue())
                
                zip_buffer.seek(0)
                
            st.success("ประมวลผลเสร็จสิ้น!")
            
            st.download_button(
                label="📥 Download Checked_Agendas.zip",
                data=zip_buffer,
                file_name="Checked_Agendas.zip",
                mime="application/zip"
            )
            st.balloons()

    else:
        st.markdown("""
            <div style="background-color: #f1f7ff; padding: 40px; border-radius: 10px; border: 2px dashed #0d6efd; text-align: center;">
                <h1 style="font-size: 3rem; margin-bottom: 10px;">📂</h1>
                <p style="font-weight: bold; color: #0d6efd;">ลากไฟล์มาวาง หรือ คลิกเพื่ออัปโหลด</p>
                <p style="font-size: 0.8rem; color: #6c757d;">รองรับไฟล์ PDF หลายไฟล์พร้อมกัน</p>
            </div>
        """, unsafe_allow_html=True)

if __name__ == '__main__':
    main()
