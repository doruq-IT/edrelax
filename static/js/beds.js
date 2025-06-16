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

const columns = calculateColumnCount(totalBeds);
bedsContainer.style.gridTemplateColumns = `repeat(${columns}, 60px)`;

// 🛏️ Şezlongları oluştur ve konum kodu (A-1 gibi) ata
for (let i = 0; i < totalBeds; i++) {
  const row = Math.floor(i / columns);
  const col = i % columns;
  const rowCode = String.fromCharCode(65 + row); // A, B, C, ...
  const bedCode = `${rowCode}-${col + 1}`;

  // Ana şezlong div'ini oluştur
  const bedDiv = document.createElement("div");
  bedDiv.classList.add("bed");
  bedDiv.dataset.id = i + 1;
  bedDiv.dataset.code = bedCode;

  const isBooked = bookedBeds.includes(i + 1);

  // Şezlong Kodunu (A-1) gösteren elementi oluştur
  const bedCodeDiv = document.createElement("div");
  bedCodeDiv.classList.add("bed-code");
  bedCodeDiv.textContent = bedCode;
  
  if (isBooked) {
    bedDiv.classList.add("booked");
    bedDiv.title = `Bu şezlong dolu. Bildirim için tıklayın.`;

    // Yeni "Boşalınca Haber Ver" katmanını oluştur
    const notifyWrapper = document.createElement("div");
    notifyWrapper.classList.add("notify-wrapper");

    // Gerekli verileri bu yeni katmana ekle
    const date = document.getElementById("selected-date")?.value;
    const start = document.getElementById("selected-start")?.value;
    const end = document.getElementById("selected-end")?.value;
    notifyWrapper.dataset.beachId = document.getElementById("reservation-wrapper")?.dataset.beachId;
    notifyWrapper.dataset.bedNumber = i + 1;
    notifyWrapper.dataset.date = date;
    notifyWrapper.dataset.timeSlot = `${start}-${end}`;
    
    // Katmanın içeriğini (ikon ve yazı) oluştur
    notifyWrapper.innerHTML = `
      <i class="fas fa-bell"></i> 
      <span class="tooltip-text">Boşalınca<br>Haber Ver</span>
    `;

    // Yeni katmanı ve şezlong kodunu ana div'e ekle
    bedDiv.appendChild(notifyWrapper);
    bedDiv.appendChild(bedCodeDiv);
    
  } else {
    // === GÜNCELLENEN BÖLÜM ===
    // Boş şezlonglar için sadece başlık ve şezlong kodunu ekle.
    // Tıklama olayı (addEventListener) bilinçli olarak buradan kaldırıldı.
    // Bu mantık bir sonraki adımda merkezi bir yerden yönetilecek.
    bedDiv.title = `Şezlong ${bedCode}`;
    
    // Sadece şezlong kodunu ekle
    bedDiv.appendChild(bedCodeDiv);
    // === GÜNCELLEME SONU ===
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
            <hr>

            <p style="
                color: #B85C00; 
                font-weight: bold; 
                font-size: 1.1em; 
                margin-top: 15px; 
                background-color: #FFF3E0; 
                padding: 10px; 
                border-radius: 5px;
                border-left: 5px solid #FF9800;">
                Ödeme plajda alınacaktır.
            </p>
          `,
          confirmButtonText: "Tamam",
          customClass: {
            popup: 'swal-wide'
          }
        }).then(() => {
          // ESKİ KOD: location.reload();
          
          // YENİ KOD: URL'yi her zaman benzersiz kılmak için zaman damgası ekle.
          // Bu, sunucu veya tarayıcı önbelleğine takılmayı engeller.
          const currentUrl = new URL(window.location.href);
          currentUrl.searchParams.set('_v', new Date().getTime()); // _v = version
          window.location.href = currentUrl.toString();
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

let currentlyTouchedBed = null;

// Tüm belgeye tıklama olayını ata (tüm tıklamaları buradan yöneteceğiz)
document.addEventListener("click", async (event) => {
  const clickedElement = event.target;

  // 1. "Boşalınca Haber Ver" katmanına mı tıklandı?
  const notifyWrapper = clickedElement.closest(".notify-wrapper");
  if (notifyWrapper) {
    // Önceki 'is-touched' durumunu temizle
    if (currentlyTouchedBed) {
      currentlyTouchedBed.classList.remove("is-touched");
      currentlyTouchedBed = null;
    }
    
    // Olayın daha fazla yayılmasını engelle
    event.stopPropagation();
    
    // Verileri al ve popup'ı göster (bu mantık değişmedi)
    const beachId = notifyWrapper.dataset.beachId;
    const bedNumber = notifyWrapper.dataset.bedNumber;
    const date = notifyWrapper.dataset.date;
    const timeSlot = notifyWrapper.dataset.timeSlot;

    if (!beachId || !bedNumber || !date || !timeSlot) {
      Swal.fire("Hata", "Şezlong bilgisi eksik.", "error");
      return;
    }

    const confirm = await Swal.fire({
      title: "Bu şezlong dolu!",
      text: "Boşalınca size haber verelim mi?",
      icon: "info",
      showCancelButton: true,
      confirmButtonText: "Evet, haber ver",
      cancelButtonText: "Hayır",
    });

    if (!confirm.isConfirmed) return;

    // Sunucuya istek gönderme (bu mantık değişmedi)
    try {
      const csrfToken = document.querySelector('meta[name="csrf-token"]')?.getAttribute('content');
      const res = await fetch("/notify-when-free", {
        method: "POST",
        headers: { "Content-Type": "application/json", ...(csrfToken && { "X-CSRFToken": csrfToken }) },
        body: JSON.stringify({ beach_id: beachId, bed_number: bedNumber, date: date, time_slot: timeSlot }),
      });
      const result = await res.json();
      if (res.ok) {
        Swal.fire("Tamamdır!", result.message || "Bildirim kaydınız alındı.", "success");
      } else {
        Swal.fire("Hata", result.message || "Bir hata oluştu", "error");
      }
    } catch (error) {
      Swal.fire("Sunucu Hatası", "Sunucuya ulaşılamadı.", "error");
    }
    return; // İşlemi burada bitir
  }

  // Tıklanan yerin bir şezlong olup olmadığını bul
  const clickedBed = clickedElement.closest(".bed");

  // Eğer dışarıya tıklandıysa ve aktif bir şezlong varsa, onu kapat
  if (!clickedBed && currentlyTouchedBed) {
    currentlyTouchedBed.classList.remove("is-touched");
    currentlyTouchedBed = null;
    return;
  }

  // Eğer bir şezlonga tıklanmadıysa, hiçbir şey yapma
  if (!clickedBed) return;

  // 2. Dolu bir şezlonga mı tıklandı? (Mobil için ilk dokunma)
  if (clickedBed.classList.contains("booked")) {
    // Başka bir şezlong zaten aktifse onu kapat
    if (currentlyTouchedBed && currentlyTouchedBed !== clickedBed) {
      currentlyTouchedBed.classList.remove("is-touched");
    }
    // Tıklanan şezlongun 'is-touched' durumunu değiştir ve takip et
    clickedBed.classList.toggle("is-touched");
    currentlyTouchedBed = clickedBed.classList.contains("is-touched") ? clickedBed : null;
  }
  
  // 3. Boş bir şezlonga mı tıklandı?
  if (!clickedBed.classList.contains("booked")) {
    // Başka bir şezlong aktifse onu kapat
    if (currentlyTouchedBed) {
      currentlyTouchedBed.classList.remove("is-touched");
      currentlyTouchedBed = null;
    }
    
    // Boş şezlong seçme mantığı (eski kodunuzdaki mantık buraya taşındı)
    const suAnSeciliOlanlarUI = document.querySelectorAll(".bed.selected").length;
    const buSezlongSeciliMi = clickedBed.classList.contains("selected");

    if (!buSezlongSeciliMi && (kullanicininOncedenRezerveEttigiSayi + suAnSeciliOlanlarUI + 1) > GUNLUK_MAKSIMUM_SEZLONG) {
      Swal.fire({
        icon: "warning",
        title: "Limit Aşıldı",
        text: `Bir günde en fazla ${GUNLUK_MAKSIMUM_SEZLONG} adet şezlong seçebilirsiniz.`,
      });
      return;
    }
    clickedBed.classList.toggle("selected");
    updatePrice();
  }
});

