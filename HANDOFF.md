# switch2-browser 引き継ぎドキュメント

## プロジェクト概要
PCブラウザからNintendo Switch 2を操作するWebUI。HDMI映像キャプチャ+コントローラーUI+AI自律操作を統合。旧switch2-mcpの「視覚層なし→廃止」の教訓を活かし、overlay+OCRで画面を「見る」設計。

## 環境
- ディレクトリ: `~/switch2-browser/`
- サーバー: `python server.py` → http://localhost:8765
- シリアル: COM3 → Arduino Nano → Pico 2 → Switch 2
- 映像: Live Gamer DUO - 1 (HDMI1)
- 依存: fastapi, uvicorn, pyserial（requirements.txt）
- フロント: Vanilla JS + Tesseract.js v7 CDN

## ファイル構成
```
switch2-browser/
├── server.py          — FastAPI + WebSocket + Serial + overlay/input/screen/state API
├── index.html         — WebUI（映像+コントローラー+overlay+OCR+全パネル）
├── requirements.txt   — Python依存
├── HANDOFF.md         — このファイル
└── games/
    └── pokemon-firered/
        ├── game-info.json    — ゲーム基本設定（30fps, 2F=66ms, タイル104px）
        ├── overlay.json      — グリッド設定（9x15, ユーザー調整済み）
        └── screens/
            ├── battle.json   — バトル画面UI（9 boxes, ユーザー調整済み）
            ├── field.json    — フィールド画面UI（textbox, ユーザー調整済み）
            └── menu.json     — メニュー画面UI（7項目, ユーザー調整済み）
```

## 現在のステータス

### 完了済み（2026-03-20）
- [x] overlay canvas（グリッド+ボックス+分割線+cellLabels+clip）
- [x] Grid UIパネル（スライダー調整+ファイル保存）
- [x] Screen UIパネル（画面種別切り替え+box編集+ドラッグ移動/リサイズ）
- [x] 入力API（/api/input/press|hold|release|stick, ゲームごとmin_frames）
- [x] ゲーム管理API（load/current/list）
- [x] State+Logパネル（リアルタイム値表示+変更履歴）
- [x] Tesseract.js OCR統合（CDN v7, jpn+eng, 変化検知→差分OCR）
- [x] HP bar解析（type:"hp_bar" → ピクセル解析で%表示）
- [x] 画面自動判別（signature方式+キャリブレーションボタン）
- [x] FPS表示（HDMI/capture/lag）
- [x] パネル折りたたみ（Controller/ScreenUI/GridOverlay/Macros/State）
- [x] ポケモンFR用 battle/field/menu のUI位置設定（ユーザーが手動調整完了）
- [x] デフォルト: キーボード入力OFF, 映像デバイス=Live Gamer DUO - 1

### ★ 現在の課題
- **OCR精度未検証**: Tesseract.js実装済みだがゲーム画面での実際のOCR精度を未確認
- **画面signature未登録**: battle/field/menuの画面自動判別用signatureがまだキャリブレーションされていない
- **HPバー解析の閾値調整**: ポケモンFRの実際のHP barの色でanalyzeHpBar()が正しく動くか未検証
- **サーバーがbashバックグラウンドで起動すると誤検知でcompleted通知が出る**: 動作自体は問題なし

### 未着手
- [ ] OCR実動作検証（ゲーム画面で各boxの読み取り精度を確認）
- [ ] 画面signatureキャリブレーション（各画面を表示→「この画面を登録」）
- [ ] AI操作ループ（スクショ→判断→入力の自動化）
- [ ] 音声キャプチャ（未実装、RME Babyface Pro WASAPI問題あり）

## 既知の罠
- bashのバックグラウンドタスク検知が`python server.py &`を誤検知してcompleted通知を出す → 無視してOK、netstatで確認
- overlay.jsonの保存は`/api/overlay/save`を呼ばないとファイルに反映されない
- サーバー再起動時にゲームのロード(`/api/games/load/pokemon-firered`)が必要
- GBAゲームのタイルサイズ=104px（6.5倍スケール）、15x10タイル
- ポケモンFRは内部30fps（60fpsではない）

## テスト実行コマンド
```bash
# サーバー起動
cd ~/switch2-browser && python server.py

# ゲーム読み込み
curl -X POST localhost:8765/api/games/load/pokemon-firered

# 画面読み込み
curl -X POST localhost:8765/api/screens/load/battle

# Aボタン押す（66ms=2F@30fps）
curl -X POST localhost:8765/api/input/press -H "Content-Type: application/json" -d '{"buttons":["a"]}'

# 現在のstate確認
curl localhost:8765/api/screen/state
```

## 次のアクション（推奨順）
1. サーバー再起動→ブラウザリロード→OCR動作確認（バトル画面でテキスト読み取り）
2. 画面signatureキャリブレーション（field→battle→menu各画面を表示して「この画面を登録」）
3. HPバー解析の精度確認・閾値調整
4. AI操作ループの設計・実装
