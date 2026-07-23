import os
import uuid
import fitz  # PyMuPDF

def convert_pdf_to_images(pdf_path, output_folder="static/uploads"):
    """
    將 PDF 檔案的每一頁轉為圖片 (.jpg)
    傳回生成圖片的檔名列表 (list of filenames)
    """
    if not os.path.exists(output_folder):
        os.makedirs(output_folder, exist_ok=True)

    doc = fitz.open(pdf_path)
    image_filenames = []
    unique_id = uuid.uuid4().hex[:8]

    for page_index in range(len(doc)):
        page = doc.load_page(page_index)
        pix = page.get_pixmap(matrix=fitz.Matrix(2, 2))  # 高解析度
        
        image_filename = f"pdf_page_{unique_id}_{page_index + 1}.jpg"
        image_path = os.path.join(output_folder, image_filename)
        
        pix.save(image_path)
        image_filenames.append(image_filename)

    doc.close()
    return image_filenames
