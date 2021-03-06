# -*- coding: utf-8 -*-
"""CNN_cls.ipynb

Automatically generated by Colaboratory.

Original file is located at
    https://colab.research.google.com/drive/1yWM3hy_obHbGvlIngKBffAudyi8Lb6hP
"""

import pandas as pd
import numpy as np
import jieba
import spacy

from sklearn.metrics import confusion_matrix
from sklearn.feature_extraction.text import CountVectorizer
from torch.nn.utils.rnn  import pack_padded_sequence ,pad_packed_sequence


import torch
import torch.nn as nn
from torch.utils import data
import torch.nn.functional as F
import random


# *------- DataLoader -------------* 
class CNNDataSet(data.Dataset):
    def __init__(self, dat_X, maxi_len, target=None):
        self.dat = dat_X
        self.target = target
        self.max_sentence_len = maxi_len
        return

    def __getitem__(self, index):
        sentence = self.dat[index]
        if len(sentence) > self.max_sentence_len:
            sentence = sentence[0:self.max_sentence_len]
        elif len(sentence) < self.max_sentence_len:
            pad_len = self.max_sentence_len - len(sentence)
            sentence = sentence + [0] * pad_len
        if self.target is not None:
            return sentence , self.target[index]
        else:
            return sentence

    def __len__(self):
        return len(self.dat)

def collate_fn_cnn(data_batch):
    data =  [s[0] for s in data_batch]
    target = [ s[-1]  for s in data_batch]
    return (torch.LongTensor(data) , torch.LongTensor(target))


class MyCNN(nn.Module):
    def __init__(self, max_len, wv_dim, class_num, cnn_channel=64 , wvmodel = None , pool_left_dim = 3 ,  embedding_num = 1000 ):
        super(MyCNN, self).__init__()
        self.conv_unigram = nn.Conv1d(in_channels=wv_dim, out_channels=cnn_channel,
                                    kernel_size=1, stride=1, padding=0)
        self.conv_2gram = nn.Conv1d(in_channels=wv_dim, out_channels=cnn_channel,
                                    kernel_size=2, stride=1, padding=1)
        self.conv_3gram = nn.Conv1d(in_channels=wv_dim, out_channels=cnn_channel,
                                    kernel_size=3, stride=1, padding=1)
        self.conv_5gram = nn.Conv1d(in_channels=wv_dim, out_channels=cnn_channel,
                                    kernel_size=5, stride=1, padding=2)
        self.Maxpool = nn.MaxPool1d(kernel_size= max_len)

        self.batch_norm = nn.BatchNorm1d(cnn_channel)
        self.dropout = nn.Dropout(p=.5)
        self.fc = nn.Linear(cnn_channel * 4 * pool_left_dim, class_num)

        self.pool = nn.AdaptiveAvgPool1d(pool_left_dim)

        # ???????????????
        self.wvmodel = wvmodel  # dictionary of {idx: vector} e.g. { 1: tensor([...]) }
        if wvmodel is not None:
            self.embedding = nn.Embedding(num_embeddings=len(wvmodel), embedding_dim=300, _weight=wvmodel)
        else:
            self.embedding = nn.Embedding(num_embeddings = embedding_num , embedding_dim=300, padding_idx=0)

    def forward(self, x):
        x = self.embedding(x)
        x = x.transpose(-2, -1) # [Batch , wv_dim , seq_len  ]
        # 1,2,3,5 -gram ?????????
        x1 = self.pool(F.relu(self.batch_norm(self.conv_unigram(x))))
        x2 = self.pool(F.relu(self.batch_norm(self.conv_2gram(x))))
        x3 = self.pool(F.relu(self.batch_norm(self.conv_3gram(x))))
        x5 = self.pool(F.relu(self.batch_norm(self.conv_5gram(x))))

        new_x = torch.cat([x1 , x2, x3, x5], dim=-1) # ??????
        new_x = new_x.view(new_x.size(0), -1)
        output = self.dropout(new_x)
        output = self.fc(output)
        return output # F.softmax

# *----------- For Neural Network -----------------*
def train(model, train_X, loss_func, optimizer):
    model.train()
    total_loss = 0
    device = torch.device("cuda:0" if torch.cuda.is_available() else "cpu")
    for i, (x, y) in enumerate(train_X):
        x = x.to(device)
        y = y.to(device)
        optimizer.zero_grad()
        output = model(x)
        loss = loss_func(output, y)
        # backward and optimize
        loss.backward()
        optimizer.step()

        total_loss += loss.item() * output.shape[0]
        if (i + 1) % 300 == 0:
            print("Step [{}/{}] Train Loss: {:.4f}".format(i + 1, len(train_X), loss.item()))

    print(total_loss / len(train_X.dataset))
    return total_loss / len(train_X.dataset)



def predict(model,test_X,SequenceClassifierOutput = False):
    # ??????prediction ??????????????????
    model.eval()
    device = torch.device("cuda:0" if torch.cuda.is_available() else "cpu")
    with torch.no_grad():
        for i , batch in enumerate(test_X):
            x , y = batch
            input_x  = x.to(device)
            output = model( input_x) # ????????????????????????????????????
            if SequenceClassifierOutput:
              output = output[0] # ???????????????????????????????????????
            if i == 0:
                pred_prob = output.detach().to('cpu').numpy()
                y_true = y
            else:
                pred_prob = np.concatenate((pred_prob, output.detach().to('cpu').numpy() ))
                y_true = np.concatenate((y_true,y))
    return pred_prob , y_true

""" # wvmodel 
 
"""

def setup_seed(seed):
     torch.manual_seed(seed)
     torch.cuda.manual_seed_all(seed)
     np.random.seed(seed)
     random.seed(seed)
     torch.backends.cudnn.deterministic = True
# ?????????????????????
setup_seed(128)
print(random.random())

def uniform_sampling(dat, maxi_each_group = 1000 ):
    groups = dat.groupby('sentiment')
    first = True
    for _, group in groups:
        if first:
            df = group.iloc[:min(maxi_each_group , len(group))]
            first = False
        else:
            df = pd.concat([df,  group.iloc[:min(maxi_each_group , len(group))] ])
    return df


def split_train_test(data, test_ratio=0.3):
  '''
  ?????? train.tsv ????????????/?????????
  :param data:
  :param test_ratio: ????????????
  :return:
  '''
  # data: dataframe
  np.random.seed(123)
  shuffled_indices = np.random.permutation(len(data))
  test_set_size = int(len(data) * test_ratio)
  test_indices = shuffled_indices[:test_set_size]
  train_indices = shuffled_indices[test_set_size:]
  return data.iloc[train_indices], data.iloc[test_indices]


def main():
    print(device)

    df = pd.read_csv("/content/drive/MyDrive/ML_data/Lyrics_AfterWash.csv")
    # ?????????
    df = df[(df['sentiment'] == 0) | (df['sentiment'] == 2)]
    df['sentiment'] = df['sentiment'].map({0: 0, 2: 1})


    train_dat, test_dat = split_train_test(df, 0.3)
    maxi_len = 200 # jieba ??????????????????

    All_text = list(df['lyric'].apply(lambda x: ' '.join([word for word in jieba.cut(x) if len(word) > 0])))
    # ?????????
    count_vec = CountVectorizer(min_df=2, max_features=500000)  # stop_words=stopWord
    _ = count_vec.fit_transform(All_text)

    idx_to_word = count_vec.get_feature_names()  # list
    word_to_idx = {word: i + 2 for i, word in enumerate(idx_to_word)}
    word_to_idx['<unk>'] = 1
    word_to_idx['<pad>'] = 0

    All_X = list(train_dat['lyric'].apply(lambda x: ' '.join([word for word in jieba.cut(x) if len(word) > 0])))
    X = [[word_to_idx.get(word, 1) for word in sentence.split(' ')] for sentence in All_X]
    y_true = list( train_dat['sentiment'] )

    train_set = CNNDataSet(dat_X = X, target=y_true, maxi_len=maxi_len)
    train_dl = data.DataLoader(dataset=train_set, batch_size=64, drop_last=False, shuffle=True,collate_fn=collate_fn_cnn)

    All_X = list(test_dat['lyric'].apply(lambda x: ' '.join([word for word in jieba.cut(x) if len(word) > 0])))
    X_test = [[word_to_idx.get(word, 1) for word in sentence.split(' ')] for sentence in All_X]
    y_true = list( test_dat['sentiment'] )
    test_set = CNNDataSet(dat_X = X_test, target=y_true, maxi_len=maxi_len)
    test_dl = data.DataLoader(dataset=test_set, batch_size=64, drop_last=False, shuffle=True,collate_fn=collate_fn_cnn)

    print(len(train_dl) , len(test_dl) )

    """# ???????????? Y"""

    def get_wordvec(word2id, vec_file_path, vec_dim=300):
      word_vectors = torch.nn.init.xavier_uniform_(torch.empty(len(word2id), vec_dim))
      word_vectors[0, :] = 0
      found = 0
      with open(vec_file_path, "r", encoding="utf-8") as f:
          _ = f.readline()  # ????????????
          lines = f.readlines()
          for line in lines:
              tmp = line.strip('\n').strip(' ').split(' ')
              word = tmp[0]
              vec = list(map(float, tmp[1:]))
              if word in word2id:
                  found += 1
                  word_vectors[word2id[word]] = torch.tensor(vec)
                  # break
              if found == len(word2id) - 1:
                  break
      return word_vectors.float()

    # From Yueyue
    vec_file_path = "/content/drive/MyDrive/sgns.wiki.word"
    wvmodel = get_wordvec(word_to_idx, vec_file_path)  # dictionary of {idx: vector} e.g. { 1: tensor([...]) }


    print('get wvmodel!!!')
    print(len(wvmodel))

    """# Train"""

    # ?????? ????????????
    model = MyCNN(max_len=maxi_len, wv_dim=300, class_num=4, cnn_channel=128 , pool_left_dim=5 ,  wvmodel=wvmodel)
    model.to(device)
    loss_func = nn.CrossEntropyLoss()
    optimizer = torch.optim.Adam( model.parameters(), lr = 5e-4 ) # ????????? < 5e-4 ?????????
    schedular = torch.optim.lr_scheduler.CosineAnnealingLR(optimizer,50,10)


    # ????????????
    print('start to train' + '*'*20)
    for epoch in range(10):
        import time
        start = time.time()
        train(model=model, train_X= train_dl, loss_func=loss_func, optimizer=optimizer)
        end = time.time()
        preb_prob , y_true = predict(model , test_dl)
        y_pred = np.argmax( preb_prob , axis = -1)
        C =confusion_matrix( y_true=y_true , y_pred=y_pred )
        print("epoch {},Run time:{} ,  ??????????????????:{}".format(epoch, end - start ,C.trace() / C.sum()))
        print('P ???R ???F1: ' , C[0,0] / (C[0,0]+C[1,0]) , C[0,0]/(C[0,0]+C[0,1]) , 2*C[0,0] / (2*C[0,0]+C[0,1]+C[1,0])  )
        print(C)

    return