from bs4 import BeautifulSoup
import re
import urllib.parse
import logging

class SeoAnalyzer:
    def __init__(self, pages_data, sitemap_urls, broken_links, skipped_pages, robot_parser):
        self.pages_data = pages_data
        self.sitemap_urls = sitemap_urls
        self.broken_links = broken_links
        self.skipped_pages = skipped_pages
        self.robot_parser = robot_parser
        self.issues = []

    def add_issue(self, url, issue_type, details, referer=None):
        self.issues.append({
            "url": url,
            "type": issue_type,
            "details": details,
            "referer": referer
        })

    def analyze(self):
        logging.info("Starting SEO analysis...")
        
        crawled_urls = set(self.pages_data.keys())
        
        # 1. Orphan pages
        for sitemap_url in self.sitemap_urls:
            if sitemap_url not in crawled_urls and sitemap_url not in self.skipped_pages:
                self.add_issue(sitemap_url, "孤兒網頁", "Sitemap 中存在，但網站內沒有任何有效連結指向它")

        # Analyze each crawled page
        for url, data in self.pages_data.items():
            html = data["html"]
            referer = data["referer"]
            soup = BeautifulSoup(html, 'lxml')
            
            # 2. Missed in Sitemap
            if url not in self.sitemap_urls:
                self.add_issue(url, "遺漏於 Sitemap", "網頁無 noindex，卻不在 sitemap.xml 中", referer=referer)

            # 4. Title < 6 chars
            title_tag = soup.find('title')
            if not title_tag or not title_tag.string or len(title_tag.string.strip()) < 6:
                length = len(title_tag.string.strip()) if title_tag and title_tag.string else 0
                self.add_issue(url, "Title 異常", f"沒有 Title 或長度少於 6 個字 (目前長度: {length})")

            # 5. Description anomaly
            desc_tag = soup.find('meta', attrs={'name': re.compile(r'^description$', re.I)})
            if not desc_tag or not desc_tag.get('content'):
                self.add_issue(url, "Description 異常", "缺少 Description")
            else:
                desc = desc_tag.get('content')
                if len(desc.strip()) < 20:
                    self.add_issue(url, "Description 異常", f"Description 過短 ({len(desc.strip())} 字)")
                elif '\n' in desc or '\r' in desc:
                    self.add_issue(url, "Description 異常", "Description 包含換行符號或異常字元")

            # 6. No canonical
            canonical_tag = soup.find('link', attrs={'rel': 'canonical'})
            if not canonical_tag or not canonical_tag.get('href'):
                self.add_issue(url, "Canonical 缺失", "缺少 canonical 網址宣告")

            # 7. Vue CSR
            if 'v-chunk' in html or 'v-if' in html or 'v-bind' in html:
                self.add_issue(url, "CSR 渲染問題", "原始碼中出現疑似 Vue 的渲染綁定語法 (v-chunk, v-if 等)")

            # 9. Viewport missing
            viewport_tag = soup.find('meta', attrs={'name': re.compile(r'^viewport$', re.I)})
            if not viewport_tag:
                self.add_issue(url, "Viewport 缺失", "沒有宣告 viewport meta 標籤")

            # 10. Charset big5
            charset_tags = soup.find_all('meta', charset=True)
            content_type_tags = soup.find_all('meta', attrs={'http-equiv': re.compile(r'^Content-Type$', re.I)})
            has_big5 = False
            for tag in charset_tags:
                if 'big5' in tag.get('charset', '').lower() or 'big-5' in tag.get('charset', '').lower():
                    has_big5 = True
            for tag in content_type_tags:
                if 'big5' in tag.get('content', '').lower() or 'big-5' in tag.get('content', '').lower():
                    has_big5 = True
            if has_big5:
                self.add_issue(url, "編碼異常", "Charset 被宣告為 big-5 或 big5，而非 utf-8")

            # 11. GTM missing/other
            gtm_scripts = re.findall(r'GTM-[A-Z0-9]+', html)
            if not gtm_scripts:
                self.add_issue(url, "GTM 異常", "未發現任何 GTM 代碼")
            else:
                if 'GTM-MRWJL2' not in gtm_scripts:
                    self.add_issue(url, "GTM 異常", f"缺少指定的 GTM-MRWJL2 (找到: {', '.join(set(gtm_scripts))})")
                other_gtms = [g for g in set(gtm_scripts) if g != 'GTM-MRWJL2']
                if other_gtms:
                    self.add_issue(url, "GTM 異常", f"混雜了其他的 GTM ID: {', '.join(other_gtms)}")

            # 12. H1 missing or > 1
            h1_tags = soup.find_all('h1')
            if len(h1_tags) == 0:
                self.add_issue(url, "H1 異常", "缺少 H1 標籤")
            elif len(h1_tags) > 1:
                self.add_issue(url, "H1 異常", f"存在 {len(h1_tags)} 個 H1 標籤 (超過 1 個)")

            # Internal links check (8 & 13)
            for a_tag in soup.find_all('a', href=True):
                href = a_tag['href']
                absolute_url = urllib.parse.urljoin(url, href)
                parsed = urllib.parse.urlparse(absolute_url)
                
                # We only care about internal links
                if parsed.scheme in ['http', 'https'] and parsed.netloc == urllib.parse.urlparse(url).netloc:
                    
                    # 13. Robots.txt violation
                    if not self.robot_parser.can_fetch("*", absolute_url):
                        self.add_issue(url, "Robots.txt 違規連結", f"網頁包含連向 robots.txt 阻擋的連結: {absolute_url}")
                    
                    # Normalize for checking
                    # simplified normalization just to match skipped_pages keys
                    norm_url = absolute_url.split('#')[0]
                    # 8. Links to noindex pages
                    if norm_url in self.skipped_pages and 'noindex' in self.skipped_pages[norm_url].get('reason', ''):
                        self.add_issue(url, "不當的內部連結", f"連向了被標記為 noindex/nofollow 的網頁: {norm_url}")

        # 3. Broken links
        for broken in self.broken_links:
            self.add_issue(broken['url'], "死結 (Broken Link)", f"狀態碼: {broken['status_code']}", referer=broken['referer'])

        logging.info(f"Analysis finished. Found {len(self.issues)} issues.")
        return self.issues
