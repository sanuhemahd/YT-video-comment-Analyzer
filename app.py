# app.py
from flask import Flask, render_template, request, session, redirect, url_for
from googleapiclient.discovery import build
from collections import Counter
from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer
from wordcloud import WordCloud
import re
import emoji
import io
import base64
import os
import json
import html

# Set your YouTube API key here
API_KEY = 'YOUR_API_KEY_HERE' 

app = Flask(__name__)
app.secret_key = os.urandom(24)

def extract_video_id(url):
    youtube_regex = (
        r'(https?://)?(www\.)?'
        '(youtube|youtu|youtube-nocookie)\\.(com|be)/'
        '(watch\\?v=|embed/|v/|.+\\?v=)?([^&=%\\?]{11})')
    match = re.match(youtube_regex, url)
    if match:
        return match.group(6)
    return url[-11:] if len(url) >= 11 else None

def clean_html_tags(text):
    text = re.sub(r'<.*?>', ' ', text)
    text = html.unescape(text)
    return text

def generate_wordcloud(text_list):
    if not text_list: return ""
    text = " ".join(text_list)
    wc = WordCloud(width=1200, height=600, background_color='#ffffff', 
                   colormap='viridis', max_words=100).generate(text)
    buf = io.BytesIO()
    wc.to_image().save(buf, format='png')
    buf.seek(0)
    return base64.b64encode(buf.getvalue()).decode('ascii')

def analyze_youtube_comments(video_url):
    try:
        video_id = extract_video_id(video_url)
        if not video_id: return {"error": "Invalid YouTube URL"}
        
        youtube = build('youtube', 'v3', developerKey=API_KEY)
        video_response = youtube.videos().list(part='snippet', id=video_id).execute()
        
        if not video_response.get('items'): return {"error": "Video not found"}
        
        video_snippet = video_response['items'][0]['snippet']
        uploader_id = video_snippet['channelId']
        video_title = video_snippet['title']
        
        raw_comments = []
        all_text = []
        nextPageToken = None
        
        while len(raw_comments) < 500:
            request_api = youtube.commentThreads().list(
                part='snippet', videoId=video_id, maxResults=100, pageToken=nextPageToken
            )
            response = request_api.execute()
            for item in response.get('items', []):
                snippet = item['snippet']['topLevelComment']['snippet']
                if snippet['authorChannelId']['value'] != uploader_id:
                    text = clean_html_tags(snippet['textDisplay'])
                    raw_comments.append({'text': text})
                    all_text.append(text.lower())
            nextPageToken = response.get('nextPageToken')
            if not nextPageToken: break

        analyzer = SentimentIntensityAnalyzer()
        polarities = [analyzer.polarity_scores(c['text'])['compound'] for c in raw_comments]

        if not polarities: return {"error": "No comments found."}

        avg_pol = sum(polarities) / len(polarities)
        pos_count = sum(1 for p in polarities if p > 0.05)
        neg_count = sum(1 for p in polarities if p < -0.05)
        neu_count = len(polarities) - (pos_count + neg_count)
        
        words = []
        stop_words = {'the', 'this', 'that', 'with', 'from', 'your', 'video', 'really', 'would', 'could'}
        for t in all_text:
            words.extend([w for w in re.findall(r'\w+', t) if len(w) > 3 and w not in stop_words])
        
        common_keywords = Counter(words).most_common(15)
        max_keyword_count = common_keywords[0][1] if common_keywords else 1
        sentiment_res = "Positive" if avg_pol > 0.05 else "Negative" if avg_pol < -0.05 else "Neutral"
        emoji_map = {"Positive": "😄", "Negative": "☹️", "Neutral": "😐"}

        return {
            "success": True,
            "video_title": video_title,
            "comments_analyzed": len(polarities),
            "avg_polarity": avg_pol,
            "sentiment_result": sentiment_res,
            "sentiment_emoji": emoji_map[sentiment_res],
            "most_positive_comment": raw_comments[polarities.index(max(polarities))]['text'],
            "most_negative_comment": raw_comments[polarities.index(min(polarities))]['text'],
            "positive_count": pos_count,
            "negative_count": neg_count,
            "neutral_count": neu_count,
            "top_keywords": common_keywords,
            "max_keyword_count": max_keyword_count,
            "wordcloud": generate_wordcloud(all_text)
        }
    except Exception as e:
        return {"error": str(e)}

@app.route('/', methods=['GET'])
def index():
    history = session.get('history', [])
    return render_template('index.html', history=history)

@app.route('/analyze', methods=['POST'])
def analyze():
    video_url = request.form.get('video_url')
    if not video_url: return redirect(url_for('index'))
    
    results = analyze_youtube_comments(video_url)
    if "error" in results: return render_template('index.html', error=results["error"], history=session.get('history', []))
    
    # Update History
    if 'history' not in session: session['history'] = []
    entry = {'title': results['video_title'], 'url': video_url}
    if entry not in session['history']:
        session['history'] = ([entry] + session['history'])[:5]
        session.modified = True
        
    return render_template('results.html', results=results)

@app.route('/clear_history')
def clear_history():
    session.pop('history', None)
    return redirect(url_for('index'))

if __name__ == '__main__':
    app.run(debug=True)