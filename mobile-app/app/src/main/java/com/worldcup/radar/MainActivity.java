package com.worldcup.radar;

import android.app.Activity;
import android.graphics.Color;
import android.graphics.Typeface;
import android.graphics.drawable.GradientDrawable;
import android.os.Bundle;
import android.os.Handler;
import android.os.Looper;
import android.text.TextUtils;
import android.view.Gravity;
import android.view.View;
import android.widget.Button;
import android.widget.HorizontalScrollView;
import android.widget.LinearLayout;
import android.widget.ProgressBar;
import android.widget.ScrollView;
import android.widget.TextView;

import org.json.JSONArray;
import org.json.JSONObject;

import java.io.BufferedReader;
import java.io.InputStream;
import java.io.InputStreamReader;
import java.net.HttpURLConnection;
import java.net.URL;
import java.nio.charset.StandardCharsets;
import java.text.SimpleDateFormat;
import java.util.ArrayList;
import java.util.Collections;
import java.util.Comparator;
import java.util.Date;
import java.util.HashMap;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.util.TimeZone;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;

public class MainActivity extends Activity {
    private static final String SCOREBOARD = "https://site.api.espn.com/apis/site/v2/sports/soccer/fifa.world/scoreboard";
    private static final String NEWS = "https://news.google.com/rss/search?q=FIFA%20World%20Cup%202026%20OR%20%E4%B8%96%E7%95%8C%E6%9D%AF%202026%20when:1d&hl=zh-CN&gl=CN&ceid=CN:zh-Hans";
    private static final int BG = Color.rgb(7, 10, 16);
    private static final int PANEL = Color.rgb(18, 26, 42);
    private static final int PANEL_SOFT = Color.rgb(25, 36, 56);
    private static final int LINE = Color.rgb(48, 63, 87);
    private static final int INK = Color.rgb(247, 251, 255);
    private static final int MUTED = Color.rgb(155, 169, 184);
    private static final int CYAN = Color.rgb(53, 212, 255);
    private static final int LIME = Color.rgb(184, 255, 79);
    private static final int CORAL = Color.rgb(255, 95, 116);

    private final ExecutorService executor = Executors.newSingleThreadExecutor();
    private final Handler main = new Handler(Looper.getMainLooper());
    private LinearLayout content;
    private TextView status;
    private ProgressBar progress;
    private List<FixtureSeed> seeds;
    private String selectedTab = "live";

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        seeds = seedFixtures();
        buildShell();
        refresh();
    }

    private void buildShell() {
        LinearLayout root = new LinearLayout(this);
        root.setOrientation(LinearLayout.VERTICAL);
        root.setBackgroundColor(BG);

        LinearLayout header = new LinearLayout(this);
        header.setOrientation(LinearLayout.VERTICAL);
        header.setPadding(dp(18), dp(16), dp(18), dp(12));
        header.setBackground(rounded(BG, 0, BG));
        root.addView(header, new LinearLayout.LayoutParams(-1, -2));

        TextView title = text("世界杯盘口校准雷达", 25, INK, true);
        header.addView(title);
        status = text("正在同步真实赛程、比分和新闻", 13, MUTED, false);
        status.setPadding(0, dp(8), 0, 0);
        header.addView(status);

        LinearLayout actions = new LinearLayout(this);
        actions.setGravity(Gravity.CENTER_VERTICAL);
        actions.setPadding(0, dp(12), 0, 0);
        header.addView(actions);

        Button refresh = pill("刷新");
        refresh.setOnClickListener(v -> refresh());
        actions.addView(refresh, new LinearLayout.LayoutParams(0, dp(44), 1));
        progress = new ProgressBar(this);
        progress.setIndeterminate(true);
        LinearLayout.LayoutParams progressParams = new LinearLayout.LayoutParams(dp(44), dp(44));
        progressParams.setMargins(dp(12), 0, 0, 0);
        actions.addView(progress, progressParams);

        HorizontalScrollView tabsScroll = new HorizontalScrollView(this);
        tabsScroll.setHorizontalScrollBarEnabled(false);
        LinearLayout tabs = new LinearLayout(this);
        tabs.setPadding(dp(14), dp(6), dp(14), dp(10));
        tabsScroll.addView(tabs);
        root.addView(tabsScroll);
        addTab(tabs, "live", "赛中");
        addTab(tabs, "fixtures", "赛程");
        addTab(tabs, "odds", "盘口");
        addTab(tabs, "news", "新闻");
        addTab(tabs, "model", "模型");

        ScrollView scroll = new ScrollView(this);
        content = new LinearLayout(this);
        content.setOrientation(LinearLayout.VERTICAL);
        content.setPadding(dp(14), dp(4), dp(14), dp(28));
        scroll.addView(content);
        root.addView(scroll, new LinearLayout.LayoutParams(-1, 0, 1));
        setContentView(root);
    }

    @Override
    protected void onDestroy() {
        executor.shutdownNow();
        super.onDestroy();
    }

    private void addTab(LinearLayout tabs, String id, String label) {
        Button button = pill(label);
        button.setOnClickListener(v -> {
            selectedTab = id;
            renderPlaceholder("切换中");
            refresh();
        });
        LinearLayout.LayoutParams params = new LinearLayout.LayoutParams(dp(86), dp(40));
        params.setMargins(0, 0, dp(8), 0);
        tabs.addView(button, params);
    }

    private void refresh() {
        progress.setVisibility(View.VISIBLE);
        status.setText("正在联网获取 ESPN 比分与世界杯新闻...");
        executor.execute(() -> {
            try {
                List<MatchState> matches = fetchScoreboard();
                List<NewsItem> news = fetchNews();
                main.post(() -> {
                    progress.setVisibility(View.GONE);
                    status.setText("已同步 " + timeNow() + " · " + matches.size() + " 场比赛 · " + news.size() + " 条新闻");
                    render(matches, news);
                });
            } catch (Exception error) {
                main.post(() -> {
                    progress.setVisibility(View.GONE);
                    status.setText("同步失败：" + error.getMessage());
                    renderOffline();
                });
            }
        });
    }

    private List<MatchState> fetchScoreboard() throws Exception {
        Map<String, MatchState> map = new HashMap<>();
        for (String date : scoreboardDates()) {
            JSONObject payload = new JSONObject(get(SCOREBOARD + "?dates=" + date));
            JSONArray events = payload.optJSONArray("events");
            if (events == null) continue;
            for (int i = 0; i < events.length(); i++) {
                MatchState match = parseEvent(events.getJSONObject(i));
                if (match != null) map.put(match.id, match);
            }
        }
        ArrayList<MatchState> list = new ArrayList<>(map.values());
        Collections.sort(list, Comparator.comparingLong(a -> a.kickoffMillis));
        return list;
    }

    private MatchState parseEvent(JSONObject event) {
        try {
            JSONObject competition = event.getJSONArray("competitions").getJSONObject(0);
            JSONArray competitors = competition.getJSONArray("competitors");
            JSONObject home = null;
            JSONObject away = null;
            for (int i = 0; i < competitors.length(); i++) {
                JSONObject item = competitors.getJSONObject(i);
                if ("home".equals(item.optString("homeAway"))) home = item;
                if ("away".equals(item.optString("homeAway"))) away = item;
            }
            if (home == null || away == null) return null;
            String homeName = home.getJSONObject("team").optString("displayName", "主队");
            String awayName = away.getJSONObject("team").optString("displayName", "客队");
            String id = event.optString("id", normalize(homeName) + "-" + normalize(awayName));
            MatchState state = new MatchState();
            state.id = id;
            state.home = zhTeam(homeName);
            state.away = zhTeam(awayName);
            state.homeRaw = homeName;
            state.awayRaw = awayName;
            state.homeGoals = parseInt(home.optString("score", "0"));
            state.awayGoals = parseInt(away.optString("score", "0"));
            state.kickoff = event.optString("date", "");
            state.kickoffMillis = parseUtc(state.kickoff);
            JSONObject statusObj = event.optJSONObject("status");
            JSONObject type = statusObj == null ? null : statusObj.optJSONObject("type");
            state.status = type == null ? "scheduled" : type.optString("state", "scheduled");
            state.detail = type == null ? "" : type.optString("shortDetail", "");
            state.minute = parseMinute(statusObj);
            FixtureSeed seed = findSeed(homeName, awayName);
            double[] lambdas = deriveLambdas(seed, state);
            state.lambdaHome = lambdas[0];
            state.lambdaAway = lambdas[1];
            Prediction prediction = predict(state);
            state.pick = prediction.score;
            state.pickProb = prediction.probability;
            state.confidence = confidence(state, prediction);
            return state;
        } catch (Exception ignored) {
            return null;
        }
    }

    private List<NewsItem> fetchNews() {
        ArrayList<NewsItem> items = new ArrayList<>();
        try {
            String xml = get(NEWS);
            String[] chunks = xml.split("<item>");
            for (int i = 1; i < chunks.length && items.size() < 12; i++) {
                String chunk = chunks[i];
                String title = stripXml(extract(chunk, "title"));
                String link = stripXml(extract(chunk, "link"));
                String pub = stripXml(extract(chunk, "pubDate"));
                if (title.length() < 4) continue;
                items.add(new NewsItem(localTranslate(title), pub, link));
            }
        } catch (Exception ignored) {
        }
        return items;
    }

    private void render(List<MatchState> matches, List<NewsItem> news) {
        content.removeAllViews();
        if ("fixtures".equals(selectedTab)) {
            renderFixtures(matches);
        } else if ("odds".equals(selectedTab)) {
            renderOdds(matches);
        } else if ("news".equals(selectedTab)) {
            renderNews(news);
        } else if ("model".equals(selectedTab)) {
            renderModel();
        } else {
            renderLive(matches);
        }
    }

    private void renderLive(List<MatchState> matches) {
        sectionTitle("赛中动态预测");
        List<MatchState> focus = new ArrayList<>();
        long now = System.currentTimeMillis();
        for (MatchState m : matches) {
            if (!"post".equals(m.status) && m.kickoffMillis > now - 3 * 60 * 60 * 1000L) focus.add(m);
        }
        if (focus.isEmpty()) focus = matches;
        for (int i = 0; i < Math.min(6, focus.size()); i++) {
            MatchState m = focus.get(i);
            LinearLayout card = card();
            card.addView(text(m.home + " vs " + m.away, 19, INK, true));
            card.addView(text(formatMatchTime(m.kickoffMillis) + " · " + stateLabel(m), 12, MUTED, false));
            TextView score = text(currentScore(m) + "  →  预测 " + m.pick, 28, LIME, true);
            score.setPadding(0, dp(12), 0, dp(6));
            card.addView(score);
            card.addView(text("主推概率 " + pct(m.pickProb) + " · 置信 " + m.confidence + "% · λ " + one(m.lambdaHome) + " / " + one(m.lambdaAway), 13, MUTED, false));
            card.addView(text(explain(m), 14, INK, false));
            content.addView(card);
        }
    }

    private void renderFixtures(List<MatchState> matches) {
        sectionTitle("未来赛程预测");
        long now = System.currentTimeMillis();
        int count = 0;
        for (MatchState m : matches) {
            if (m.kickoffMillis < now - 90 * 60 * 1000L) continue;
            LinearLayout card = card();
            card.addView(text(formatMatchTime(m.kickoffMillis), 12, MUTED, false));
            card.addView(text(m.home + "  " + m.pick + "  " + m.away, 21, INK, true));
            card.addView(text("状态：" + stateLabel(m) + " · 动态置信 " + m.confidence + "%", 13, MUTED, false));
            content.addView(card);
            count++;
            if (count >= 12) break;
        }
        if (count == 0) renderPlaceholder("暂时没有未来赛程，稍后刷新。");
    }

    private void renderOdds(List<MatchState> matches) {
        sectionTitle("盘口与赔率摘要");
        for (int i = 0; i < Math.min(8, matches.size()); i++) {
            MatchState m = matches.get(i);
            LinearLayout card = card();
            card.addView(text(m.home + " vs " + m.away, 18, INK, true));
            card.addView(text("本机 App 第一版不接商业赔率 Key；先用 ESPN 比分、时间、赛前 λ 和进球状态估算盘口倾向。", 13, MUTED, false));
            card.addView(text("倾向：" + outcomeLabel(m) + " · 参考波胆 " + m.pick + " · " + decimalOdds(m.pickProb) + "倍", 18, CYAN, true));
            content.addView(card);
        }
    }

    private void renderNews(List<NewsItem> news) {
        sectionTitle("世界杯热点新闻");
        if (news.isEmpty()) {
            renderPlaceholder("新闻源暂时不可用，稍后刷新。");
            return;
        }
        for (NewsItem item : news) {
            LinearLayout card = card();
            card.addView(text(item.title, 17, INK, true));
            card.addView(text(item.published, 12, MUTED, false));
            if (!TextUtils.isEmpty(item.link)) {
                card.addView(text(item.link, 11, CYAN, false));
            }
            content.addView(card);
        }
    }

    private void renderModel() {
        sectionTitle("模型说明");
        LinearLayout card = card();
        card.addView(text("本地泊松 + 赛中贝叶斯修正", 20, INK, true));
        card.addView(text("App 会把赛前 λ 当先验，再根据当前比分、比赛分钟、强弱差和比赛状态调整剩余进球期望。它不是简单地“谁进球就继续看谁”，而是让领先方降速、落后方提高冒险权重。", 14, MUTED, false));
        card.addView(text("数据源：ESPN 公开 scoreboard + Google News RSS。商业博彩实时数据需要合法 API Key，后续可以接入 The Odds API。", 14, MUTED, false));
        content.addView(card);
    }

    private void renderOffline() {
        content.removeAllViews();
        sectionTitle("离线预测");
        for (FixtureSeed seed : seeds.subList(0, Math.min(8, seeds.size()))) {
            MatchState m = new MatchState();
            m.home = seed.home;
            m.away = seed.away;
            m.lambdaHome = seed.lambdaHome;
            m.lambdaAway = seed.lambdaAway;
            Prediction p = predict(m);
            LinearLayout card = card();
            card.addView(text(seed.home + " vs " + seed.away, 18, INK, true));
            card.addView(text("预测 " + p.score + " · 概率 " + pct(p.probability), 20, LIME, true));
            content.addView(card);
        }
    }

    private Prediction predict(MatchState m) {
        double homeBase = m.lambdaHome;
        double awayBase = m.lambdaAway;
        double remaining = 1.0;
        if ("in".equals(m.status) && m.minute > 0) {
            remaining = Math.max(0.08, (96.0 - Math.min(m.minute, 96)) / 96.0);
            int diff = m.homeGoals - m.awayGoals;
            if (diff > 0) {
                homeBase *= 0.82;
                awayBase *= 1.14;
            } else if (diff < 0) {
                homeBase *= 1.14;
                awayBase *= 0.82;
            }
        } else if ("post".equals(m.status)) {
            return new Prediction(m.homeGoals + "-" + m.awayGoals, 1.0);
        }
        double hRemain = clamp(homeBase * remaining, 0.05, 3.5);
        double aRemain = clamp(awayBase * remaining, 0.05, 3.5);
        String best = "0-0";
        double bestP = -1;
        for (int h = 0; h <= 6; h++) {
            for (int a = 0; a <= 6; a++) {
                int finalH = m.homeGoals + h;
                int finalA = m.awayGoals + a;
                double p = poisson(h, hRemain) * poisson(a, aRemain);
                if (p > bestP) {
                    bestP = p;
                    best = finalH + "-" + finalA;
                }
            }
        }
        return new Prediction(best, bestP);
    }

    private double[] deriveLambdas(FixtureSeed seed, MatchState state) {
        if (seed != null) return new double[]{seed.lambdaHome, seed.lambdaAway};
        double home = 1.35;
        double away = 1.05;
        String h = state.homeRaw.toLowerCase(Locale.US);
        String a = state.awayRaw.toLowerCase(Locale.US);
        home += teamBoost(h);
        away += teamBoost(a);
        return new double[]{clamp(home, 0.45, 3.0), clamp(away, 0.45, 3.0)};
    }

    private double teamBoost(String name) {
        if (name.contains("spain") || name.contains("france") || name.contains("argentina") || name.contains("brazil") || name.contains("england") || name.contains("portugal") || name.contains("germany")) return 0.75;
        if (name.contains("uruguay") || name.contains("belgium") || name.contains("netherlands") || name.contains("croatia") || name.contains("colombia")) return 0.38;
        if (name.contains("haiti") || name.contains("qatar") || name.contains("curacao") || name.contains("jordan") || name.contains("panama")) return -0.28;
        return 0;
    }

    private FixtureSeed findSeed(String home, String away) {
        String h = normalize(home);
        String a = normalize(away);
        for (FixtureSeed seed : seeds) {
            if (normalize(seed.homeRaw).equals(h) && normalize(seed.awayRaw).equals(a)) return seed;
            if (normalize(seed.home).equals(h) && normalize(seed.away).equals(a)) return seed;
        }
        return null;
    }

    private List<String> scoreboardDates() {
        ArrayList<String> dates = new ArrayList<>();
        long day = 24L * 60L * 60L * 1000L;
        SimpleDateFormat fmt = new SimpleDateFormat("yyyyMMdd", Locale.US);
        fmt.setTimeZone(TimeZone.getTimeZone("UTC"));
        long now = System.currentTimeMillis();
        for (int offset = -2; offset <= 2; offset++) dates.add(fmt.format(new Date(now + offset * day)));
        return dates;
    }

    private String get(String urlText) throws Exception {
        HttpURLConnection connection = (HttpURLConnection) new URL(urlText).openConnection();
        connection.setConnectTimeout(9000);
        connection.setReadTimeout(12000);
        connection.setRequestProperty("Accept", "application/json, application/rss+xml, text/xml, */*");
        connection.setRequestProperty("User-Agent", "WorldCupRadarAndroid/1.0");
        try (InputStream input = connection.getInputStream()) {
            BufferedReader reader = new BufferedReader(new InputStreamReader(input, StandardCharsets.UTF_8));
            StringBuilder builder = new StringBuilder();
            String line;
            while ((line = reader.readLine()) != null) builder.append(line);
            return builder.toString();
        } finally {
            connection.disconnect();
        }
    }

    private LinearLayout card() {
        LinearLayout card = new LinearLayout(this);
        card.setOrientation(LinearLayout.VERTICAL);
        card.setPadding(dp(16), dp(14), dp(16), dp(14));
        card.setBackground(rounded(PANEL, 16, LINE));
        LinearLayout.LayoutParams params = new LinearLayout.LayoutParams(-1, -2);
        params.setMargins(0, 0, 0, dp(12));
        card.setLayoutParams(params);
        return card;
    }

    private void sectionTitle(String value) {
        TextView title = text(value, 22, INK, true);
        title.setPadding(0, dp(8), 0, dp(12));
        content.addView(title);
    }

    private void renderPlaceholder(String value) {
        content.removeAllViews();
        LinearLayout card = card();
        card.addView(text(value, 16, MUTED, false));
        content.addView(card);
    }

    private TextView text(String value, int sp, int color, boolean bold) {
        TextView text = new TextView(this);
        text.setText(value);
        text.setTextSize(sp);
        text.setTextColor(color);
        text.setLineSpacing(dp(2), 1.0f);
        if (bold) text.setTypeface(Typeface.DEFAULT, Typeface.BOLD);
        return text;
    }

    private Button pill(String label) {
        Button button = new Button(this);
        button.setText(label);
        button.setTextColor(INK);
        button.setTextSize(13);
        button.setAllCaps(false);
        button.setBackground(rounded(PANEL_SOFT, 18, LINE));
        return button;
    }

    private GradientDrawable rounded(int color, int radiusDp, int strokeColor) {
        GradientDrawable drawable = new GradientDrawable();
        drawable.setColor(color);
        drawable.setCornerRadius(dp(radiusDp));
        drawable.setStroke(dp(1), strokeColor);
        return drawable;
    }

    private int dp(int value) {
        return (int) (value * getResources().getDisplayMetrics().density + 0.5f);
    }

    private String currentScore(MatchState m) {
        return ("pre".equals(m.status) || "scheduled".equals(m.status)) ? "赛前" : m.homeGoals + "-" + m.awayGoals;
    }

    private String stateLabel(MatchState m) {
        if ("in".equals(m.status)) return "进行中 " + Math.max(m.minute, 0) + "'";
        if ("post".equals(m.status)) return "已完场";
        return "未开赛";
    }

    private String outcomeLabel(MatchState m) {
        String[] parts = m.pick.split("-");
        if (parts.length != 2) return "观察";
        int h = parseInt(parts[0]);
        int a = parseInt(parts[1]);
        if (h > a) return "主胜";
        if (h < a) return "客胜";
        return "平局";
    }

    private String explain(MatchState m) {
        if ("in".equals(m.status)) {
            return "赛中修正：分钟越靠后，剩余 λ 越低；领先方略降速，落后方提高压上权重。";
        }
        if ("post".equals(m.status)) return "比赛已结束，用真实比分回看模型偏差。";
        return "赛前修正：根据球队强弱种子、公开赛程和泊松比分分布给出主推。";
    }

    private int confidence(MatchState m, Prediction p) {
        int base = (int) Math.round(clamp(p.probability * 340, 36, 82));
        if ("in".equals(m.status)) base += Math.min(12, Math.max(0, m.minute / 8));
        if ("post".equals(m.status)) base = 100;
        return Math.min(96, base);
    }

    private double poisson(int k, double lambda) {
        return Math.pow(lambda, k) * Math.exp(-lambda) / factorial(k);
    }

    private int factorial(int value) {
        int result = 1;
        for (int i = 2; i <= value; i++) result *= i;
        return result;
    }

    private double clamp(double value, double low, double high) {
        return Math.max(low, Math.min(high, value));
    }

    private int parseInt(String value) {
        try {
            return Integer.parseInt(value.replaceAll("[^0-9-]", ""));
        } catch (Exception ignored) {
            return 0;
        }
    }

    private int parseMinute(JSONObject status) {
        if (status == null) return 0;
        String combined = status.optString("displayClock") + " " + status.optJSONObject("type");
        java.util.regex.Matcher matcher = java.util.regex.Pattern.compile("(\\d+)").matcher(combined);
        if (matcher.find()) return parseInt(matcher.group(1));
        return 0;
    }

    private long parseUtc(String iso) {
        String[] patterns = {
                "yyyy-MM-dd'T'HH:mm:ss.SSS'Z'",
                "yyyy-MM-dd'T'HH:mm:ss'Z'",
                "yyyy-MM-dd'T'HH:mm'Z'"
        };
        for (String pattern : patterns) {
            try {
                SimpleDateFormat fmt = new SimpleDateFormat(pattern, Locale.US);
                fmt.setTimeZone(TimeZone.getTimeZone("UTC"));
                Date parsed = fmt.parse(iso);
                if (parsed != null) return parsed.getTime();
            } catch (Exception ignored) {
            }
        }
        return System.currentTimeMillis() + 365L * 24L * 60L * 60L * 1000L;
    }

    private String formatMatchTime(long millis) {
        SimpleDateFormat fmt = new SimpleDateFormat("M月d日 HH:mm", Locale.CHINA);
        fmt.setTimeZone(TimeZone.getTimeZone("Asia/Shanghai"));
        return fmt.format(new Date(millis));
    }

    private String timeNow() {
        SimpleDateFormat fmt = new SimpleDateFormat("HH:mm:ss", Locale.CHINA);
        fmt.setTimeZone(TimeZone.getTimeZone("Asia/Shanghai"));
        return fmt.format(new Date());
    }

    private String pct(double value) {
        return Math.round(value * 100) + "%";
    }

    private String one(double value) {
        return String.format(Locale.CHINA, "%.1f", value);
    }

    private String decimalOdds(double probability) {
        if (probability <= 0.01) return "99";
        return String.format(Locale.CHINA, "%.1f", Math.min(99.0, 1.0 / probability));
    }

    private String normalize(String value) {
        return value == null ? "" : value.toLowerCase(Locale.US).replaceAll("[^a-z0-9\\u4e00-\\u9fa5]+", " ").trim();
    }

    private String extract(String chunk, String tag) {
        String start = "<" + tag + ">";
        String end = "</" + tag + ">";
        int s = chunk.indexOf(start);
        int e = chunk.indexOf(end);
        if (s < 0 || e < 0 || e <= s) return "";
        return chunk.substring(s + start.length(), e);
    }

    private String stripXml(String value) {
        return value == null ? "" : value.replace("<![CDATA[", "").replace("]]>", "").replaceAll("<[^>]+>", "").trim();
    }

    private String localTranslate(String text) {
        String value = text;
        value = value.replace("World Cup", "世界杯")
                .replace("FIFA", "国际足联")
                .replace("Spain", "西班牙")
                .replace("France", "法国")
                .replace("Norway", "挪威")
                .replace("Portugal", "葡萄牙")
                .replace("Brazil", "巴西")
                .replace("England", "英格兰")
                .replace("Germany", "德国")
                .replace("updates", "动态")
                .replace("odds", "赔率")
                .replace("goal", "进球");
        return value;
    }

    private String zhTeam(String name) {
        Map<String, String> map = new HashMap<>();
        map.put("Spain", "西班牙");
        map.put("Cape Verde", "佛得角");
        map.put("Belgium", "比利时");
        map.put("Egypt", "埃及");
        map.put("Saudi Arabia", "沙特");
        map.put("Uruguay", "乌拉圭");
        map.put("Iran", "伊朗");
        map.put("New Zealand", "新西兰");
        map.put("France", "法国");
        map.put("Senegal", "塞内加尔");
        map.put("Iraq", "伊拉克");
        map.put("Norway", "挪威");
        map.put("Argentina", "阿根廷");
        map.put("Algeria", "阿尔及利亚");
        map.put("Austria", "奥地利");
        map.put("Jordan", "约旦");
        map.put("Portugal", "葡萄牙");
        map.put("Congo DR", "民主刚果");
        map.put("England", "英格兰");
        map.put("Croatia", "克罗地亚");
        map.put("Ghana", "加纳");
        map.put("Panama", "巴拿马");
        map.put("Uzbekistan", "乌兹别克斯坦");
        map.put("Colombia", "哥伦比亚");
        map.put("Czechia", "捷克");
        map.put("South Africa", "南非");
        map.put("Switzerland", "瑞士");
        map.put("Bosnia and Herzegovina", "波黑");
        map.put("Canada", "加拿大");
        map.put("Qatar", "卡塔尔");
        map.put("Mexico", "墨西哥");
        map.put("South Korea", "韩国");
        map.put("United States", "美国");
        map.put("Australia", "澳大利亚");
        map.put("Brazil", "巴西");
        map.put("Germany", "德国");
        map.put("Netherlands", "荷兰");
        map.put("Japan", "日本");
        return map.containsKey(name) ? map.get(name) : name;
    }

    private List<FixtureSeed> seedFixtures() {
        ArrayList<FixtureSeed> list = new ArrayList<>();
        list.add(new FixtureSeed("Spain", "Cape Verde", "西班牙", "佛得角", 3.1, 0.8));
        list.add(new FixtureSeed("Belgium", "Egypt", "比利时", "埃及", 1.65, 1.05));
        list.add(new FixtureSeed("Saudi Arabia", "Uruguay", "沙特", "乌拉圭", 0.75, 1.75));
        list.add(new FixtureSeed("Iran", "New Zealand", "伊朗", "新西兰", 1.05, 0.85));
        list.add(new FixtureSeed("France", "Senegal", "法国", "塞内加尔", 1.7, 1.0));
        list.add(new FixtureSeed("Iraq", "Norway", "伊拉克", "挪威", 0.65, 1.85));
        list.add(new FixtureSeed("Argentina", "Algeria", "阿根廷", "阿尔及利亚", 2.1, 0.65));
        list.add(new FixtureSeed("Austria", "Jordan", "奥地利", "约旦", 1.75, 0.75));
        list.add(new FixtureSeed("Portugal", "Congo DR", "葡萄牙", "民主刚果", 2.45, 0.85));
        list.add(new FixtureSeed("England", "Croatia", "英格兰", "克罗地亚", 1.9, 1.05));
        list.add(new FixtureSeed("Czechia", "South Africa", "捷克", "南非", 1.35, 1.05));
        list.add(new FixtureSeed("Canada", "Qatar", "加拿大", "卡塔尔", 1.65, 0.95));
        list.add(new FixtureSeed("Mexico", "South Korea", "墨西哥", "韩国", 1.35, 1.25));
        list.add(new FixtureSeed("Brazil", "Haiti", "巴西", "海地", 2.8, 0.45));
        list.add(new FixtureSeed("Germany", "Ivory Coast", "德国", "科特迪瓦", 2.15, 0.95));
        return list;
    }

    private static class FixtureSeed {
        final String homeRaw;
        final String awayRaw;
        final String home;
        final String away;
        final double lambdaHome;
        final double lambdaAway;

        FixtureSeed(String homeRaw, String awayRaw, String home, String away, double lambdaHome, double lambdaAway) {
            this.homeRaw = homeRaw;
            this.awayRaw = awayRaw;
            this.home = home;
            this.away = away;
            this.lambdaHome = lambdaHome;
            this.lambdaAway = lambdaAway;
        }
    }

    private static class MatchState {
        String id;
        String home;
        String away;
        String homeRaw;
        String awayRaw;
        String kickoff;
        String status;
        String detail;
        int minute;
        int homeGoals;
        int awayGoals;
        long kickoffMillis;
        double lambdaHome;
        double lambdaAway;
        String pick;
        double pickProb;
        int confidence;
    }

    private static class Prediction {
        final String score;
        final double probability;

        Prediction(String score, double probability) {
            this.score = score;
            this.probability = probability;
        }
    }

    private static class NewsItem {
        final String title;
        final String published;
        final String link;

        NewsItem(String title, String published, String link) {
            this.title = title;
            this.published = published;
            this.link = link;
        }
    }
}
