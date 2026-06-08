import os
import urllib.request
from urllib.error import URLError, HTTPError

def fetch_ffd_contours():
    url = "https://www.dragmetostorm.com/wfo/FFDetector/FFDetector_Contours.txt"
    output_dir = "static"
    output_file = os.path.join(output_dir, "ffd_contours.txt")

    # Ensure the static directory exists before trying to save
    os.makedirs(output_dir, exist_ok=True)

    print(f"Fetching FFD Contours from {url}...")
    
    # Passing a User-Agent header prevents the remote server from blocking the automated script
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'})
    
    try:
        with urllib.request.urlopen(req, timeout=15) as response:
            content = response.read().decode('utf-8', errors='ignore')
            
            with open(output_file, 'w', encoding='utf-8') as f:
                f.write(content)
                
            print(f"Successfully downloaded FFD Contours. Saved to {output_file}.")
            
    except HTTPError as e:
        print(f"HTTP Error: {e.code} - {e.reason}")
    except URLError as e:
        print(f"URL Error: {e.reason}")
    except Exception as e:
        print(f"An unexpected error occurred: {e}")

if __name__ == "__main__":
    fetch_ffd_contours()
