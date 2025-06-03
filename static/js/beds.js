const bedsContainer = document.getElementById("beds-container");
const checkoutBtn = document.getElementById("checkout-btn");
const totalPriceEl = document.getElementById("total-price");
let selectedBedsInfoEl = document.getElementById("selected-beds-info");

// 💡 Kolon sayısını dinamik hesapla
function calculateColumnCount(total) {
  if (total <= 5) return total;
  if (total <= 10) return 5;
  if (total <= 15) return 6;
  if (total <= 20) return 7;
  if (total <= 30) return 8;
  if (total <= 50) return 9;
  return 10;
}

// Bu değişkenlerin select_beds.html içindeki <script> bloğunda tanımlandığını varsayıyoruz:
// const totalBeds = {{ beach.bed_count or 20 }};
// const bookedBeds = {{ booked_beds | tojson }};
// const bedPrice = {{ beach.price or 10 }};
// const kullanicininOncedenRezerveEttigiSayi = {{ kullanicinin_o_gun_rezerve_ettigi_sezlong_sayisi | default(0) | tojson }};
// const GUNLUK_MAKSIMUM_SEZLONG = 10;

const columns = calculateColumnCount(totalBeds);
bedsContainer.style.gridTemplateColumns = `repeat(${columns}, 60px)`;

// 🛏️ Şezlongları oluştur ve konum kodu (A-1 gibi) ata
for (let i = 0; i < totalBeds; i++) {
  const row = Math.floor(i / columns);
  const col = i % columns;
  const rowCode = String.fromCharCode(65 + row); // A, B, C, ...
  const bedCode = `${rowCode}-${col + 1}`;

  const bedDiv = document.createElement("div");
  bedDiv.classList.add("bed");
  bedDiv.dataset.id = i + 1;
  bedDiv.dataset.code = bedCode;
  bedDiv.title = `Şezlong ${bedCode}`;

  const isBooked = bookedBeds.includes(i + 1);
  if (isBooked) {
    bedDiv.classList.add("booked");
    bedDiv.title += " (DOLU)";
  } else {
    bedDiv.addEventListener("click", () => {
      const suAnSeciliOlanlarUI = document.querySelectorAll(".bed.selected").length;
      const buSezlongSeciliMi = bedDiv.classList.contains("selected");

      // Eğer kullanıcı yeni bir şezlong seçmeye çalışıyorsa (yani bu şezlong henüz seçili değilse)
      // ve bu seçimle birlikte günlük limiti aşacaksa:
      if (!buSezlongSeciliMi &&
          (kullanicininOncedenRezerveEttigiSayi + suAnSeciliOlanlarUI + 1) > GUNLUK_MAKSIMUM_SEZLONG) {
        Swal.fire({
          icon: "warning",
          title: "Limit Aşıldı",
          text: "Bir günde en fazla " + GUNLUK_MAKSIMUM_SEZLONG + " adet şezlong seçebilirsiniz. Daha fazlası için lütfen iletişime geçin."
        });
        return; // Şezlongun seçilmesini engelle
      }

      // Limit aşılmadıysa veya kullanıcı bir seçimi kaldırıyorsa
      bedDiv.classList.toggle("selected");
      updatePrice();
    });
  }

  bedsContainer.appendChild(bedDiv);
}

// 💰 Fiyatı ve seçilen şezlongları güncelle
function updatePrice() {
  const selectedBeds = document.querySelectorAll(".bed.selected");
  const count = selectedBeds.length;
  totalPriceEl.textContent = count * bedPrice;

  if (selectedBedsInfoEl) {
    const selectedCodes = Array.from(selectedBeds)
      .map(b => b.dataset.code)
      .join(", ");
    selectedBedsInfoEl.textContent = selectedCodes || "Yok";
  }
}

// 🕒 Geri sayım süresi (saniye cinsinden)
let countdown = 180;
const countdownEl = document.getElementById("countdown-timer");

function formatTime(sec) {
  const m = String(Math.floor(sec / 60)).padStart(2, '0');
  const s = String(sec % 60).padStart(2, '0');
  return `${m}:${s}`;
}

// 🔁 Her saniye güncelle
const countdownInterval = setInterval(() => {
  countdown--;
  if (countdownEl) countdownEl.textContent = formatTime(countdown);

  if (countdown <= 0) {
    clearInterval(countdownInterval);
    Swal.fire({
      icon: "info",
      title: "Süre Doldu",
      text: "Seçim süreniz sona erdi. Sayfa yeniden yüklenecek.",
      timer: 4000,
      showConfirmButton: false
    }).then(() => {
      location.reload();
    });
  }
}, 1000);

// 🚀 Check Out ve Rezervasyon Kaydı
checkoutBtn.addEventListener("click", () => {
  const selectedBeds = document.querySelectorAll(".bed.selected");
  if (selectedBeds.length === 0) {
    Swal.fire({
      icon: "warning",
      title: "Seçim yapılmadı",
      text: "Lütfen en az bir şezlong seçin."
    });
    return;
  }

  const date = document.getElementById("selected-date")?.value;
  const start = document.getElementById("selected-start")?.value;
  const end = document.getElementById("selected-end")?.value;
  const beachId = document.getElementById("reservation-wrapper").dataset.beachId;

  if (!date || !start || !end || !beachId) {
    Swal.fire({
      icon: "error",
      title: "Eksik bilgi",
      text: "Rezervasyon verileri eksik."
    });
    return;
  }

  // Ödeme butonuna tıklandığında da limit kontrolü
  if ((kullanicininOncedenRezerveEttigiSayi + selectedBeds.length) > GUNLUK_MAKSIMUM_SEZLONG) {
    Swal.fire({
      icon: "error",
      title: "Limit Aşıldı!",
      text: "Günlük maksimum şezlong limitini (" + GUNLUK_MAKSIMUM_SEZLONG + ") aştınız. Lütfen seçiminizi gözden geçirin veya daha fazla şezlong için bizimle iletişime geçin.",
      confirmButtonText: "Anladım"
    });
    return; // Ödeme işlemini durdur
  }

  // ⛔ Double-click koruması
  checkoutBtn.disabled = true;
  checkoutBtn.innerText = "Gönderiliyor...";

  // ⏹ Sayaç durdurulsun
  clearInterval(countdownInterval);

  const bedIds = Array.from(selectedBeds).map(bed => parseInt(bed.dataset.id));
  const totalPrice = bedIds.length * bedPrice;

  const payload = {
    beach_id: parseInt(beachId),
    bed_ids: bedIds,
    date: date,
    start_time: start,
    end_time: end
  };

  const csrfToken = document.querySelector('meta[name="csrf-token"]').getAttribute('content');

  fetch("/make-reservation", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "X-CSRFToken": csrfToken
    },
    body: JSON.stringify(payload)
  })
    .then(res => res.json())
    .then(data => {
      if (data.success) {
        const selectedCodes = Array.from(selectedBeds)
          .map(b => b.dataset.code)
          .join(', ');
        Swal.fire({
          icon: "success",
          title: "Rezervasyon Tamamlandı!",
          html: `
            <p>📅 <strong>${date}</strong></p>
            <p>⏰ <strong>${start} - ${end}</strong></p>
            <p>🪑 <strong>${bedIds.length}</strong> adet şezlong</p>
            <p>🔖 <strong>${selectedCodes}</strong></p>
            <p>💸 <strong>${totalPrice} TL</strong></p>
          `,
          confirmButtonText: "Tamam",
          customClass: {
            popup: 'swal-wide'
          }
        }).then(() => {
          location.reload();
        });
      } else {
        Swal.fire({
          icon: "error",
          title: "Hata",
          text: data.message || "Rezervasyon oluşturulamadı."
        });
        checkoutBtn.disabled = false;
        checkoutBtn.innerText = "Ödemeye Geç";
      }
    })
    .catch(err => {
      console.error("Hata:", err);
      Swal.fire({
        icon: "error",
        title: "Sunucu hatası",
        text: "Bir hata oluştu. Lütfen tekrar deneyin."
      });
      checkoutBtn.disabled = false;
      checkoutBtn.innerText = "Ödemeye Geç";
    });
});