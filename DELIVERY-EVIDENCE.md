# أدلة التسليم — PS4 Linux Desktop / Delivery evidence

> هذه الوثيقة تصف **تشغيلًا موجودًا بالفعل**. لم يُعَد البناء، ولم يُحذف أي ملف.
> Every fact below was read back from the GitHub API for that run; nothing is reconstructed or guessed.

---

## 1. الهوية الدقيقة / Identity

| العنصر | القيمة |
|---|---|
| المستودع (كامل) | `sbshsjh067-tech/PS4-Linux-Desktop` (public) |
| رابط المستودع | https://github.com/sbshsjh067-tech/PS4-Linux-Desktop |
| الفرع | `arena/d2ccd0a7-ps4-linux-desktop` |
| **Commit الذي بُني منه فعلًا (build SHA)** | `2c02664bb0de7d06fda0c05a622785e7d070059a` |
| رأس الفرع الآن (branch head) | `e7a62b6f20cc16979faf13c2d29867b661176ccf` — توثيق فقط، **لم يُعِد البناء** |
| التشغيل الناجح | **run `43642717115`** |
| النوع / المحاولة | `push` / attempt `1` |
| البدء → الانتهاء (UTC) | `2026-11-14T21:25:15Z` → `2026-11-14T21:46:08Z` (≈20m53s) |
| النتيجة | **success** |

---

## 2. روابط GitHub Actions

- **التشغيل:** https://github.com/sbshsjh067-tech/PS4-Linux-Desktop/actions/runs/43642717115
- **الـworkflow:** https://github.com/sbshsjh067-tech/PS4-Linux-Desktop/actions/workflows/external-build.yml

| Job | id | النتيجة | الرابط |
|---|---|---|---|
| Repository unit tests (TEST A..N) | `132593600476` | success | https://github.com/sbshsjh067-tech/PS4-Linux-Desktop/actions/runs/43642717115/job/132593600476 |
| Build kernel + linux.img + fPKG (ubuntu-24.04) | `132593642233` | success | https://github.com/sbshsjh067-tech/PS4-Linux-Desktop/actions/runs/43642717115/job/132593642233 |

روابط مباشرة إلى الخطوات المطلوبة داخل job البناء:

- Stage 6 — build the real fPKG → `#step:12:1`
  https://github.com/sbshsjh067-tech/PS4-Linux-Desktop/actions/runs/43642717115/job/132593642233#step:12:1
- Stage 7 — structural verification + PFS round-trip → `#step:13:1`
  https://github.com/sbshsjh067-tech/PS4-Linux-Desktop/actions/runs/43642717115/job/132593642233#step:13:1
- Stage 8 — upload to tmpfiles.org → `#step:14:1`
  https://github.com/sbshsjh067-tech/PS4-Linux-Desktop/actions/runs/43642717115/job/132593642233#step:14:1
- Publish summary (URL + digests) → `#step:17:1`
  https://github.com/sbshsjh067-tech/PS4-Linux-Desktop/actions/runs/43642717115/job/132593642233#step:17:1

> ملاحظة: GitHub يطلب تسجيل الدخول لعرض سجلات Actions حتى في المستودعات العامة، ولتنزيل الـartifacts.

---

## 3. الـArtifacts الناتجة (3) — كلها `expired=false`

| الـartifact | id | الحجم | ينتهي | رابط الواجهة | رابط الـAPI (zip) |
|---|---|---|---|---|---|
| `ps4-linux-desktop-fpkg` | `14133009227` | 16,268,490 B | 2026-11-28T21:46:04Z | https://github.com/sbshsjh067-tech/PS4-Linux-Desktop/actions/runs/43642717115/artifacts/14133009227 | https://api.github.com/repos/sbshsjh067-tech/PS4-Linux-Desktop/actions/artifacts/14133009227/zip |
| `ps4-linux-desktop-boot-assets` | `14132914619` | 14,282,879 B | 2026-11-28T21:46:03Z | https://github.com/sbshsjh067-tech/PS4-Linux-Desktop/actions/runs/43642717115/artifacts/14132914619 | https://api.github.com/repos/sbshsjh067-tech/PS4-Linux-Desktop/actions/artifacts/14132914619/zip |
| `ps4-linux-desktop-external-reports` | `14133069210` | 79,596 B | 2026-11-28T21:46:02Z | https://github.com/sbshsjh067-tech/PS4-Linux-Desktop/actions/runs/43642717115/artifacts/14133069210 | https://api.github.com/repos/sbshsjh067-tech/PS4-Linux-Desktop/actions/artifacts/14133069210/zip |

المحتوى (كما هو مأخوذ من `.github/workflows/external-build.yml`):

- **fpkg:** `artifacts/external/pkg/*.pkg` → `IV0000-BREW00001_00-PS4LDESKTOP00000.pkg`
- **boot-assets:** `kernel/bzImage`, `kernel/kernel.config`, `kexec.bin`, `orbis/eboot.bin`, `orbis/libc.prx`, `orbis/libSceFios2.prx`, `orbis/right.sprx`
- **external-reports:** `build.log`, `BUILD-LOG.md`, **`SHA256SUMS`**, `pkg-report.json`, `pkg-inspection.json`, `pkg-upload.json`, `pkg-extract.log`, `pkg-build.stderr`, `pkgtool-probe.out`, `pkg-report-attempt*.json`

---

## 4. الملفات النهائية: ما هو موجود كرابط وما هو غير موجود

### 4.1 ملف PKG — الرابط المباشر الوحيد
لا يوجد URL عام للـ`.pkg` نفسه (لم يُرفع إلى أي استضافة عامة دائمة)؛ التسليم الرسمي هو الـartifact:

```
gh run download 43642717115 -R sbshsjh067-tech/PS4-Linux-Desktop \
  -n ps4-linux-desktop-fpkg -D ./delivery
# الناتج: ./delivery/IV0000-BREW00001_00-PS4LDESKTOP00000.pkg
```
أو من المتصفح بعد تسجيل الدخول: https://github.com/sbshsjh067-tech/PS4-Linux-Desktop/actions/runs/43642717115/artifacts/14133009227

### 4.2 ملف `linux.img` — **لا يوجد رابط، وهذا حدّ معروف**
- أُنتج فعلًا في **Stage 5** (Debian 12 bookworm، `ROOTFS_PROFILE=xorg`، `ROOTFS_SIZE=6G`) ونجح.
- لكنه **غير مُدرج في أي artifact** (الـworkflow يرفع فقط `bzImage`/`kexec`/`eboot`/PRX والـ`.pkg`)، و**غير مرفوع** إلى tmpfiles.org (الرفع يخصّ الـ`.pkg` فقط).
- لذلك: لا رابط مباشر لـ`linux.img` اليوم. قيمة SHA-256 الخاصة به **مسجّلة** في `SHA256SUMS` (داخل artifact التقارير) عبر `record_artifact "Debian … ext4 root filesystem (linux.img)"`.
- لإنتاج نسخة قابلة للتحميل لاحقًا (دون إعادة بناء الـ.pkg): رفع الـ`linux.img` كـartifact أو إلى تخزين خارجي — قرار لم يُنفّذ بعد.

### 4.3 رابط tmpfiles.org — موجود لكن غير قابل للقراءة من هنا
- الرابط الحقيقي مكتوب في **`pkg-upload.json`** (داخل artifact التقارير) وظهر في سجل Stage 8 وفي ملخّص الـjob.
- في هذا الـsandbox تعذّر قراءته: سجلات Actions ونزول الـartifacts يمرّان عبر `results-receiver.actions.githubusercontent.com` / `productionresultssa3.blob.core.windows.net` وهما محجوبان، وصفحة الـjob تطلب تسجيل دخول.
- **لم أخترع أي رابط.** للحصول عليه:
```
gh run download 43642717115 -R sbshsjh067-tech/PS4-Linux-Desktop \
  -n ps4-linux-desktop-external-reports -D ./reports
python3 -c "import json;d=json.load(open('./reports/pkg-upload.json'));print(d['url']);print(d.get('direct_url'))"
```
- تنبيه مهم: tmpfiles.org يحتفظ بالملفات **~60 دقيقة** فقط (الرفع كان 21:46Z). إن انتهت صلاحيته فالـartifact أعلاه هو النسخة الدائمة؛ إعادة الرفع ممكنة **بدون إعادة بناء**:
```
./bin/ps4-pkg-packager upload ./delivery/IV0000-BREW00001_00-PS4LDESKTOP00000.pkg
```

---

## 5. قيم SHA-256 — أين توجد بالضبط

| ما تبحث عنه | الموقع الدقيق | كيف تقرأه |
|---|---|---|
| `.pkg`, `bzImage`, `kernel.config`, `kexec.bin`, `eboot.bin`, `libc.prx`, `libSceFios2.prx`, `right.sprx`, `linux.img` | سطر واحد لكل ملف داخل `artifacts/external/SHA256SUMS` | `cat ./reports/SHA256SUMS` |
| أدقّ نسخة من الـ.pkg | `pkg-inspection.json` → `sha256`, `size_bytes`, `header_pkg_size`, `pfs_image_offset/size` | `python3 -m json.tool ./reports/pkg-inspection.json` |
| سجل التحقق لحظة البناء | `build.log` (سطر `sha256: …`) و`BUILD-LOG.md` | `grep -E "sha256|size:" ./reports/build.log` |

> لا أستطيع استخراج هذه القيم داخل هذه الجلسة (الحجب أعلاه)، ولن أُدرج قيمًا مُخمّنة. الأرقام موجودة فعلًا في الـartifact القابل للتنزيل بأمر واحد.

---

## 6. سجل Stage 6 / Stage 7 / Stage 8 (وقائع التشغيل)

| # | الخطوة | الحالة | البدء (UTC) | الانتهاء (UTC) | الأمر المنفَّذ |
|---|---|---|---|---|---|
| 12 | Stage 6/8 — build the real fPKG | **success** | 21:45:54 | 21:45:58 | `./bin/ps4-pkg-packager build-or-stage … --pkgtool <LibOrbisPkg PkgTool.Core>` (كائن .NET مبني من المصدر @ `72370ca…`) |
| 13 | Stage 7/8 — structural verification + PFS round-trip | **success** | 21:45:58 | 21:46:00 | `inspect-pkg`, `inspect-sfo`, `od` header dump، ثم `PkgTool.Core pkg_extract --passcode 000…0` + مقارنة SHA-256 |
| 14 | Stage 8/8 — upload to tmpfiles.org | **success** | 21:46:00 | 21:46:02 | `ps4-pkg-packager upload <pkg>` + تحقق `curl -I` من الـURL (HTTP 200 ومطابقة Content-Length) |
| 15 | Stage 8/8 — skipped (--no-upload) | skipped | — | — | مسار بديل لم يُستخدم |

النصوص الكاملة للسجلات موجودة في `build.log` داخل artifact التقارير، أو بالنقر على روابط `#step:…` في القسم 2 بعد تسجيل الدخول.

---

## 7. التحقق البنيوي للـPKG — دقيق ومحدَّد

ما **يثبته** خروج Stage 7 بالرمز 0 (السكربت يُخفق بـ`exit 1` عند أي فشل بنيوي):

1. بايتات السحر عند `0x00` = `7f 43 4e 54` (`\x7fCNT`) — تُطبع في السجل وفي `pkg-inspection.json`.
2. `valid_ps4_pkg = true` من `inspect-pkg`، مع تفكيك رأس CNT: `content_id`, `entry_count`, `header_pkg_size`, `pfs_image_offset`, `pfs_image_size`.
3. قراءة `param.sfo` بنجاح عبر `inspect-sfo`.
4. عند التنفيذ: استخراج كامل بـ`pkg_extract --passcode 0000…` (32 صفرًا) ومقارنة SHA-256 لثلاثة ملفات (`eboot.bin`, `assets/boot/bzImage`, `assets/boot/kexec.bin`) — أي اختلاف يُفشل الخطوة فورًا.

**تحفّظ واحد للأمانة:** إذا فشلت أداة الاستخراج نفسها يتحوّل الأمر إلى تحذير (`pkg_extract failed … round-trip unproven`) ولا تُفشل الخطوة؛ لذلك تأكيد الـround-trip الفعلي يتطلّب رؤية `pkg-extract.log` أو سطر `round-trip MATCH` في `build.log` (كلاهما في الـartifact). ثبوت الرأس (`\x7fCNT` + `valid_ps4_pkg=true`) مضمون بخروج Stage 7 ناجحًا.

### ما لم يُختبر — بصراحة
- **لم يُختبر على جهاز PS4 حقيقي إطلاقًا.** لا Sony SDK، لا أجهزة، لا تهيئة على أجهزة فعلية.
- الـ`.pkg` هو **fPKG بتوقيع وهمي**: `create-fself --paid 0x3800000000000011` وpasscode تجريبي من 32 صفرًا ⇒ يحتاج **GoldHEN/HEN** ولا يعمل على نظام Sony الرسمي.
- لم يُتحقّق من قبول `SceAppInstUtil` لبيانات PlayGo/chunk داخل هذا الـPKG.
- `linux.img` (Debian 12، بروفايل `xorg`) لم يُقلع على الجهاز؛ `initramfs`/`kexec` مبنيان لكن سلسلة الإقلاع الحقيقية غير مثبتة تجريبيًا.

---

## 8. أوامر النسخ الكامل (تنزيل كل شيء مرة واحدة)

```bash
REPO=sbshsjh067-tech/PS4-Linux-Desktop
RUN=43642717115
gh run download "$RUN" -R "$REPO" -n ps4-linux-desktop-fpkg        -D ./delivery
gh run download "$RUN" -R "$REPO" -n ps4-linux-desktop-external-reports -D ./reports
gh run download "$RUN" -R "$REPO" -n ps4-linux-desktop-boot-assets -D ./boot
cat ./reports/SHA256SUMS                 # كل البصمات + linux.img
python3 -m json.tool ./reports/pkg-inspection.json   # تحقق بنيوي مفصّل
python3 -c "import json;print(json.load(open('./reports/pkg-upload.json'))['url'])"  # رابط tmpfiles
```
