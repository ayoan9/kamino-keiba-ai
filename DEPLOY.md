# 外部共有メモ

Wi-Fi外のユーザーに共有する場合は、MacローカルURLではなく公開サーバーへデプロイします。
このMVPはDocker対応済みなので、まずはRenderの無料Web Serviceが一番シンプルです。

## Renderで公開する流れ

1. このフォルダをGitHubリポジトリへアップロードする
2. Renderで「New Web Service」→ GitHubリポジトリを選択
3. `render.yaml` を使って作成する
4. Environment Variablesに必要な値を入れる

推奨設定:

| 変数名 | 用途 |
| --- | --- |
| `APP_ACCESS_PASSWORD` | 共有用パスワード。設定するとログイン画面が出ます |
| `OPENAI_API_KEY` | 画像解析やOpenAI評価を使う場合だけ設定 |
| `KAMINO_DATA_DIR` | 任意。永続Diskを使う場合は `/var/data` を指定 |
| `SUPABASE_URL` | 任意。Supabase保存を使う場合のProject URL |
| `SUPABASE_SERVICE_ROLE_KEY` | 任意。Supabase保存を使う場合のservice_roleキー |
| `SUPABASE_TABLE` | 任意。省略時は `kamino_store` |

公開後はRenderが発行する `https://...onrender.com` のURLを共有します。

## 自動保存を残すためのRender Disk設定

RenderのWeb Serviceは、通常のコンテナ内ファイルが再起動・再デプロイで消えることがあります。予想AIの下書き、買い目実績ラボの下書き、予想方針、実績、Web傾向キャッシュを継続して残す場合は、Web ServiceにDiskを1つ追加してください。

1. Render Dashboardで `kamino-keiba-ai` のWeb Serviceを開く
2. 左メニューの「Disks」を開く
3. 「Add Disk」を押す
4. Nameは `kamino-data` など任意
5. Mount Pathを `/var/data` にする
6. Sizeはまず `1 GB` でOK
7. 保存後、サービスを再デプロイまたは再起動する

アプリは `/var/data` が書き込み可能なら自動的にそこへ保存します。明示したい場合はEnvironment Variablesに `KAMINO_DATA_DIR=/var/data` も追加してください。

## Render無料枠で自動保存を残すSupabase設定

Render Diskが使えない場合は、Supabaseの無料枠を保存先にします。Renderは画面表示、Supabaseは下書き・実績・予想方針の保存箱として使います。

### 1. Supabaseでプロジェクトを作る

1. Supabaseで新規Projectを作成
2. Project Settings → APIを開く
3. `Project URL` を控える
4. `service_role` のsecret keyを控える

`service_role` keyは管理者用の秘密鍵です。GitHubには書かず、RenderのEnvironment Variablesにだけ入れてください。

### 2. SQL Editorで保存用テーブルを作る

SupabaseのSQL Editorで以下を1回だけ実行します。

```sql
create table if not exists public.kamino_store (
  scope text not null,
  key text not null,
  payload jsonb not null,
  updated_at timestamptz not null default now(),
  primary key (scope, key)
);
```

このアプリはサーバー側から `service_role` keyで保存するため、まずはRLSポリシーを追加しなくても動かせます。

### 3. Renderに環境変数を入れる

Render Dashboard → Web Service → Environment で以下を追加します。

| 変数名 | 入れる値 |
| --- | --- |
| `SUPABASE_URL` | SupabaseのProject URL |
| `SUPABASE_SERVICE_ROLE_KEY` | Supabaseのservice_role secret key |
| `SUPABASE_TABLE` | `kamino_store` |

保存後にRenderを再デプロイしてください。アプリのサイドバーに保存先として `Supabase + ローカル` が表示されれば、クラウド保存が有効です。

Supabaseが未設定、または一時的に通信できない場合も、アプリはローカルJSON保存へフォールバックします。

## 軽量運用の方針

- 画像・PDFアップロード上限は25MBに制限しています。
- 予想履歴のサイドバー表示は最新50件までです。
- 作業途中の内容はURL内の下書きIDごとに、予想AIは `data/drafts/`、買い目実績ラボは `data/lab_drafts/` へ自動一時保存されます。Supabase設定時は同じ内容をSupabaseにも保存します。Render Disk利用時は `/var/data/drafts/` と `/var/data/lab_drafts/` に保存されます。
- 公開版でもAPIキーなしで人気上位オッズ表画像を読み取れます。まず固定レイアウトOCRで数字セルだけを切り出し、必要に応じてTesseract無料OCRへ切り替えます。OpenAI APIキーは読み取り補助が必要な場合だけ使います。
- Web傾向取得、JRAオッズ取得、PDF/画像出力はボタンを押した時だけ動きます。
- 公開サーバーではMac専用OCRは表示されません。標準PDF解析かOpenAI API解析を使います。
- 永続Diskを追加していない無料サーバーのローカルJSONは再起動で消える場合があります。大事な予想はJSONを書き出してください。

## 注意

少人数のクラブ内共有ならこの構成で十分です。
利用者別に履歴を分けたい、本格的に予想結果を蓄積したい、無人で定刻取得したい場合は、ログイン機能・外部DB・定期実行基盤を追加するのが次の段階です。
