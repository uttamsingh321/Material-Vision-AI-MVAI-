import openpyxl
from openpyxl.drawing.image import Image as XLImage
import io
import asyncio
import httpx
import re
import urllib.parse
from app.main import extract_core_keywords

input_file = "c:/Users/uttam.singh1/Desktop/FINAL_Material_Master_Template.xlsx"

async def main():
    print("Loading workbook...")
    wb = openpyxl.load_workbook(input_file)
    ws = wb.active
    
    # Identify missing rows
    image_rows = set(img.anchor._from.row + 1 for img in ws._images)
    missing_rows = [r for r in range(2, ws.max_row + 1) if r not in image_rows]
    print(f"Found {len(missing_rows)} missing rows.")
    
    semaphore = asyncio.Semaphore(40)
    
    async def process_row(row):
        desc = ws.cell(row=row, column=5).value or ws.cell(row=row, column=4).value or ws.cell(row=row, column=3).value
        if not desc: return
        query = extract_core_keywords(desc)
        if not query: return
        
        async with semaphore:
            try:
                search_url = f"https://www.bing.com/images/search?q={urllib.parse.quote_plus(query + ' industrial')}"
                async with httpx.AsyncClient(timeout=10, follow_redirects=True) as client:
                    r = await client.get(search_url, headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"})
                    m = re.search(r'murl&quot;:&quot;(.*?)&quot;', r.text)
                    if not m:
                        return
                    img_url = m.group(1)
                    
                    img_resp = await client.get(img_url, headers={"User-Agent": "Mozilla/5.0"})
                    return row, img_resp.content
            except Exception:
                return None
        return None
                
    tasks = [process_row(r) for r in missing_rows]
    
    completed = 0
    for task in asyncio.as_completed(tasks):
        res = await task
        if res:
            row, img_bytes = res
            try:
                from PIL import Image
                import mimetypes
                # Add .mpo just in case
                if True in mimetypes.types_map: mimetypes.types_map[True]['.mpo'] = 'image/jpeg'
                
                # Convert everything to standard JPEG
                img = Image.open(io.BytesIO(img_bytes))
                if img.mode != 'RGB':
                    img = img.convert('RGB')
                out_stream = io.BytesIO()
                img.save(out_stream, format='JPEG')
                out_stream.seek(0)
                
                xl_img = XLImage(out_stream)
                xl_img.width = 80
                xl_img.height = 80
                cell_addr = f"G{row}"
                ws.add_image(xl_img, cell_addr)
                ws.row_dimensions[row].height = 65
            except Exception as e:
                pass
        completed += 1
        if completed % 50 == 0:
            print(f"Processed {completed}/{len(missing_rows)}")
            
    print("Saving...")
    wb.save(input_file)
    print("Done!")

if __name__ == "__main__":
    asyncio.run(main())
