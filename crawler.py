import requests
from bs4 import BeautifulSoup
import urllib.parse
import xml.etree.ElementTree as ET
from urllib.robotparser import RobotFileParser
import re
import time
import logging

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

class DigiwinCrawler:
    def __init__(self, start_url="https://www.digiwin.com.tw/", max_pages=0):
        self.start_url = start_url
        self.domain = urllib.parse.urlparse(start_url).netloc
        self.base_url = f"https://{self.domain}"
        self.max_pages = max_pages
        
        self.visited = set()
        self.queue = [] # list of dicts: {"url": url, "referer": referer}
        
        self.sitemap_urls = set()
        self.pages_data = {}  # {url: {"html": html_content, "referer": referer}}
        self.broken_links = [] # [{"url": target_url, "referer": source_url, "status_code": code}]
        self.skipped_pages = {} # {url: {"reason": reason}}
        
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
        })
        
        self.robot_parser = RobotFileParser()

    def load_robots_txt(self):
        robots_url = urllib.parse.urljoin(self.base_url, "/robots.txt")
        logging.info(f"Loading robots.txt from {robots_url}")
        self.robot_parser.set_url(robots_url)
        try:
            self.robot_parser.read()
        except Exception as e:
            logging.error(f"Failed to read robots.txt: {e}")

    def load_sitemap(self):
        sitemap_url = urllib.parse.urljoin(self.base_url, "/sitemap.xml")
        logging.info(f"Loading sitemap from {sitemap_url}")
        try:
            response = self.session.get(sitemap_url, timeout=15)
            response.raise_for_status()
            
            root = ET.fromstring(response.content)
            # Handle XML namespaces correctly
            namespaces = {'ns': 'http://www.sitemaps.org/schemas/sitemap/0.9'}
            for loc in root.findall('.//ns:loc', namespaces):
                if loc.text:
                    normalized = self.normalize_url(loc.text)
                    self.sitemap_urls.add(normalized)
            logging.info(f"Found {len(self.sitemap_urls)} URLs in sitemap.")
        except Exception as e:
            logging.error(f"Failed to load or parse sitemap: {e}")

    def normalize_url(self, url):
        parsed = urllib.parse.urlparse(url)
        
        # Remove fragment
        parsed = parsed._replace(fragment='')
        
        # Remove tracking query parameters (like utm_*)
        query_params = urllib.parse.parse_qsl(parsed.query, keep_blank_values=True)
        filtered_params = [(k, v) for k, v in query_params if not k.startswith('utm_')]
        
        new_query = urllib.parse.urlencode(filtered_params)
        parsed = parsed._replace(query=new_query)
        
        # Ensure it ends with a standard format if needed, but here we just rebuild
        # Also remove trailing slash for consistency (unless it's just the root domain)
        normalized = urllib.parse.urlunparse(parsed)
        if normalized != self.base_url + "/" and normalized.endswith('/'):
            normalized = normalized[:-1]
            
        return normalized

    def is_internal_and_valid(self, url):
        parsed = urllib.parse.urlparse(url)
        
        # Must be same domain
        if parsed.netloc and parsed.netloc != self.domain:
            return False
            
        # Ignore specific paths
        if parsed.path.startswith('/search'):
            return False
        if parsed.path.startswith('/tag/'):
            return False
        if parsed.path.startswith('/zlsq'):
            return False
            
        # Ignore mailto, tel, javascript, etc.
        if parsed.scheme and parsed.scheme not in ['http', 'https']:
            return False
            
        return True

    def process_head(self, url):
        try:
            resp = self.session.head(url, timeout=10, allow_redirects=False)
            
            # Handle Redirects
            if resp.status_code in [301, 302, 307, 308]:
                location = resp.headers.get('Location')
                if not location:
                    return {"valid": False, "reason": f"Redirect status {resp.status_code} but no Location header", "status": resp.status_code}
                
                target_url = self.normalize_url(urllib.parse.urljoin(url, location))
                if self.is_internal_and_valid(target_url):
                    return {
                        "valid": False, 
                        "reason": f"Redirected to internal URL: {target_url}", 
                        "status": resp.status_code, 
                        "redirect_type": "internal", 
                        "redirect_target": target_url
                    }
                else:
                    return {
                        "valid": False, 
                        "reason": f"Redirected to external domain: {target_url}", 
                        "status": resp.status_code, 
                        "redirect_type": "external", 
                        "redirect_target": target_url
                    }
            
            if resp.status_code in [403, 404]:
                return {"valid": False, "status": resp.status_code}
                
            if resp.status_code != 200:
                # Other errors are soft ignored or handled
                return {"valid": False, "status": resp.status_code}
                
            # Check Content-Type
            content_type = resp.headers.get('Content-Type', '').lower()
            if 'text/html' not in content_type:
                return {"valid": False, "reason": f"Non-HTML content type: {content_type}"}
                
            # Check X-Robots-Tag
            x_robots = resp.headers.get('X-Robots-Tag', '').lower()
            if 'noindex' in x_robots:
                return {"valid": False, "reason": "X-Robots-Tag: noindex"}
                
            return {"valid": True, "status": 200}
        except Exception as e:
            return {"valid": False, "reason": str(e), "status": 0}

    def fetch_and_extract(self, url, referer):
        logging.info(f"Fetching: {url}")
        try:
            resp = self.session.get(url, timeout=15)
            html = resp.text
            
            # Fast check for meta noindex without full parse if possible, but bs4 is robust
            soup = BeautifulSoup(html, 'lxml')
            meta_robots = soup.find('meta', attrs={'name': re.compile(r'^robots$', re.I)})
            if meta_robots and 'noindex' in meta_robots.get('content', '').lower():
                logging.info(f"Skipping {url} (meta robots noindex)")
                self.skipped_pages[url] = {"reason": "meta robots noindex"}
                return None
                
            # Store valid page data
            self.pages_data[url] = {
                "html": html,
                "referer": referer
            }
            
            # Extract links
            for a_tag in soup.find_all('a', href=True):
                href = a_tag['href']
                absolute_url = urllib.parse.urljoin(url, href)
                norm_url = self.normalize_url(absolute_url)
                
                # We need to process this link
                if self.is_internal_and_valid(norm_url):
                    if norm_url not in self.visited:
                        # Only add to queue if not already visited
                        # We also don't want the queue to grow forever with duplicates, so check if it's already in queue
                        if not any(item['url'] == norm_url for item in self.queue):
                            self.queue.append({"url": norm_url, "referer": url})
                            
            return True
            
        except Exception as e:
            logging.error(f"Error fetching {url}: {e}")
            return None

    def crawl(self, progress_callback=None, progress_interval=10):
        logging.info("Starting crawler...")
        self.load_robots_txt()
        self.load_sitemap()

        start_norm = self.normalize_url(self.start_url)
        self.queue.append({"url": start_norm, "referer": None})

        pages_crawled = 0

        while self.queue:
            if self.max_pages > 0 and pages_crawled >= self.max_pages:
                logging.info(f"Reached max pages limit ({self.max_pages}). Stopping crawl.")
                break

            current = self.queue.pop(0)
            url = current["url"]
            referer = current["referer"]

            if url in self.visited:
                continue

            self.visited.add(url)

            # Perform HEAD check
            head_result = self.process_head(url)

            if not head_result["valid"]:
                # Check if it was a redirect to an internal page
                if head_result.get("redirect_type") == "internal":
                    target_url = head_result["redirect_target"]
                    # If target_url has not been visited and is not already in the queue, add it
                    if target_url not in self.visited and not any(item['url'] == target_url for item in self.queue):
                        self.queue.append({"url": target_url, "referer": referer})
                        logging.info(f"Redirect from {url} to internal {target_url} added to queue.")
                
                if head_result.get("status") in [403, 404]:
                    self.broken_links.append({
                        "url": url,
                        "referer": referer,
                        "status_code": head_result["status"]
                    })
                else:
                    self.skipped_pages[url] = {"reason": head_result.get('reason', f'Status {head_result.get("status")}')}
                logging.debug(f"Skipped {url}: {head_result.get('reason', f'Status {head_result.get('status')}')}")
                continue

            # Perform GET and extract
            success = self.fetch_and_extract(url, referer)
            if success:
                pages_crawled += 1
                if progress_callback and pages_crawled % progress_interval == 0:
                    logging.info(f"Progress checkpoint: {pages_crawled} pages crawled, triggering report update.")
                    progress_callback(self.pages_data, self.sitemap_urls, self.broken_links, self.skipped_pages, self.robot_parser)

            # Polite delay
            time.sleep(0.5)

        logging.info(f"Crawl finished. Processed {pages_crawled} valid pages.")
        return self.pages_data, self.sitemap_urls, self.broken_links, self.skipped_pages, self.robot_parser

if __name__ == "__main__":
    crawler = DigiwinCrawler(max_pages=5)
    data, sitemap, broken, skipped, rp = crawler.crawl()
    print(f"Crawled {len(data)} pages.")
