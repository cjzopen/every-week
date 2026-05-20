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
            metadata = data.get("metadata", {})
            referer = data["referer"]
            
            # 2. Missed in Sitemap
            if url not in self.sitemap_urls:
                canonical = metadata.get("canonical", "")
                if not canonical or canonical not in self.sitemap_urls:
                    self.add_issue(url, "遺漏於 Sitemap", "網頁無 noindex，卻不在 sitemap.xml 中", referer=referer)

            # 4. Title < 6 chars
            title = metadata.get("title", "")
            if not title or len(title.strip()) < 6:
                length = len(title.strip()) if title else 0
                self.add_issue(url, "Title 異常", f"沒有 Title 或長度少於 6 個字 (目前長度: {length})")

            # 5. Description anomaly
            desc = metadata.get("description", "")
            if not desc:
                self.add_issue(url, "Description 異常", "缺少 Description")
            else:
                if len(desc.strip()) < 20:
                    self.add_issue(url, "Description 異常", f"Description 過短 ({len(desc.strip())} 字)")
                elif '\n' in desc or '\r' in desc:
                    self.add_issue(url, "Description 異常", "Description 包含換行符號或異常字元")

            # 6. No canonical
            canonical = metadata.get("canonical", "")
            if not canonical:
                self.add_issue(url, "Canonical 缺失", "缺少 canonical 網址宣告")

            # 7. Vue CSR
            if metadata.get("has_vue_csr", False):
                self.add_issue(url, "CSR 渲染問題", "原始碼中出現疑似 Vue 的渲染綁定語法 (v-chunk, v-if 等)")

            # 9. Viewport missing
            if not metadata.get("has_viewport", False):
                self.add_issue(url, "Viewport 缺失", "沒有宣告 viewport meta 標籤")

            # 10. Charset big5
            if metadata.get("has_big5", False):
                self.add_issue(url, "編碼異常", "Charset 被宣告為 big-5 或 big5，而非 utf-8")

            # 11. GTM missing/other
            gtm_scripts = metadata.get("gtms", [])
            if not gtm_scripts:
                self.add_issue(url, "GTM 異常", "未發現 any GTM 代碼")
            else:
                if 'GTM-MRWJL2' not in gtm_scripts:
                    self.add_issue(url, "GTM 異常", f"缺少指定的 GTM-MRWJL2 (找到: {', '.join(set(gtm_scripts))})")
                other_gtms = [g for g in set(gtm_scripts) if g != 'GTM-MRWJL2']
                if other_gtms:
                    self.add_issue(url, "GTM 異常", f"混雜了其他的 GTM ID: {', '.join(other_gtms)}")

            # 12. H1 missing or > 1
            h1_count = metadata.get("h1_count", 0)
            if h1_count == 0:
                self.add_issue(url, "H1 異常", "缺少 H1 標籤")
            elif h1_count > 1:
                self.add_issue(url, "H1 異常", f"存在 {h1_count} 個 H1 標籤 (超過 1 個)")

            # Internal links check (8 & 13)
            for absolute_url in metadata.get("internal_links", []):
                # 13. Robots.txt violation
                if not self.robot_parser.can_fetch("*", absolute_url):
                    self.add_issue(url, "Robots.txt 違規連結", f"網頁包含連向 robots.txt 阻擋的連結: {absolute_url}")
                
                # Normalize for checking
                norm_url = absolute_url.split('#')[0]
                # 8. Links to noindex pages
                if norm_url in self.skipped_pages and 'noindex' in self.skipped_pages[norm_url].get('reason', ''):
                    self.add_issue(url, "不當的內部連結", f"連向了被標記為 noindex/nofollow 的網頁: {norm_url}")

        # 3. Broken links
        for broken in self.broken_links:
            self.add_issue(broken['url'], "死結 (Broken Link)", f"狀態碼: {broken['status_code']}", referer=broken['referer'])

        logging.info(f"Analysis finished. Found {len(self.issues)} issues.")
        return self.issues
