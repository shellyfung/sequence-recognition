# -*- coding: utf-8 -*-

"""辣鸡代码"""

import os, sys, string
import sys
import logging
import multiprocessing
import time
import json
import cv2
import numpy as np
from sklearn.model_selection import train_test_split

import keras
import keras.backend as K
from keras.datasets import mnist
from keras.models import *
from keras.layers import *
from keras.optimizers import *
from keras.callbacks import *
from keras import backend as K
# from keras.utils.visualize_util import plot
from visual_callbacks import AccLossPlotter

plotter = AccLossPlotter(graphs=['acc', 'loss'], save_graph=True, save_graph_path=sys.path[0])

# 识别字符集
char_ocr = '0123456789'  # string.digits
# 定义识别字符串的最大长度
seq_len = 8
# 识别结果集合个数 0-9
label_count = len(char_ocr) + 1


def get_label(filepath):
  # print(str(os.path.split(filepath)[-1]).split('.')[0].split('_')[-1])
  lab = []
  for num in str(os.path.split(filepath)[-1]).split('.')[0].split('_')[-1]:
    lab.append(int(char_ocr.find(num)))
  if len(lab) < seq_len:
    cur_seq_len = len(lab)
    for i in range(seq_len - cur_seq_len):
      lab.append(label_count)  #
  return lab


def gen_image_data(dir=r'data\train', file_list=[]):
  dir_path = dir
  for rt, dirs, files in os.walk(dir_path):  # =pathDir
    for filename in files:
      # print (filename)
      if filename.find('.') >= 0:
        (shotname, extension) = os.path.splitext(filename)
        # print shotname,extension
        if extension == '.tif':  # extension == '.png' or
          file_list.append(os.path.join('%s\\%s' % (rt, filename)))
          # print (filename)

  print(len(file_list))
  index = 0
  X = []
  Y = []
  for file in file_list:
    index += 1
    # if index>1000:
    #     break
    # print(file)
    img = cv2.imread(file, 0)
    # print(np.shape(img))
    # cv2.namedWindow("the window")
    # cv2.imshow("the window",img)
    # 操，还是定长图像
    img = cv2.resize(img, (150, 50), interpolation=cv2.INTER_CUBIC)
    img = cv2.transpose(img, (50, 150))
    img = cv2.flip(img, 1)
    # cv2.namedWindow("the window")
    # cv2.imshow("the window",img)
    # cv2.waitKey()
    img = (255 - img) / 256  # 反色处理
    X.append([img])
    Y.append(get_label(file))
    # print(get_label(file))
    # print(np.shape(X))
    # print(np.shape(X))

  # print(np.shape(X))
  X = np.transpose(X, (0, 2, 3, 1))
  X = np.array(X)
  Y = np.array(Y)
  return X, Y


# the actual loss calc occurs here despite it not being
# an internal Keras loss function

def ctc_lambda_func(args):
  y_pred, labels, input_length, label_length = args
  # the 2 is critical here since the first couple outputs of the RNN
  # tend to be garbage:
  # y_pred = y_pred[:, 2:, :] 测试感觉没影响
  y_pred = y_pred[:, :, :]
  return K.ctc_batch_cost(labels, y_pred, input_length, label_length)


if __name__ == '__main__':
  height = 150
  width = 50
  input_tensor = Input((height, width, 1))
  x = input_tensor
  for i in range(3):
    x = Convolution2D(32 * 2 ** i, (3, 3), activation='relu', padding='same')(x)
    # x = Convolution2D(32*2**i, (3, 3), activation='relu')(x)
    x = MaxPooling2D(pool_size=(2, 2))(x)

  conv_shape = x.get_shape()
  # print(conv_shape)
  x = Reshape(target_shape=(int(conv_shape[1]), int(conv_shape[2] * conv_shape[3])))(x)

  x = Dense(32, activation='relu')(x)

  gru_1 = GRU(32, return_sequences=True, kernel_initializer='he_normal', name='gru1')(x)
  gru_1b = GRU(32, return_sequences=True, go_backwards=True, kernel_initializer='he_normal', name='gru1_b')(x)
  gru1_merged = add([gru_1, gru_1b])  ###################

  gru_2 = GRU(32, return_sequences=True, kernel_initializer='he_normal', name='gru2')(gru1_merged)
  gru_2b = GRU(32, return_sequences=True, go_backwards=True, kernel_initializer='he_normal', name='gru2_b')(
    gru1_merged)
  x = concatenate([gru_2, gru_2b])  ######################
  x = Dropout(0.25)(x)
  x = Dense(label_count, kernel_initializer='he_normal', activation='softmax')(x)
  base_model = Model(inputs=input_tensor, outputs=x)

  labels = Input(name='the_labels', shape=[seq_len], dtype='float32')
  input_length = Input(name='input_length', shape=[1], dtype='int64')
  label_length = Input(name='label_length', shape=[1], dtype='int64')
  loss_out = Lambda(ctc_lambda_func, output_shape=(1,), name='ctc')([x, labels, input_length, label_length])

  model = Model(inputs=[input_tensor, labels, input_length, label_length], outputs=[loss_out])
  model.compile(loss={'ctc': lambda y_true, y_pred: y_pred}, optimizer='adadelta')
  model.summary()


  def test(base_model):
    file_list = []
    X, Y = gen_image_data(r'data\test', file_list)
    y_pred = base_model.predict(X)
    shape = y_pred[:, :, :].shape  # 2:
    out = K.get_value(K.ctc_decode(y_pred[:, :, :], input_length=np.ones(shape[0]) * shape[1])[0][0])[:,
          :seq_len]  # 2:
    print()
    error_count = 0
    for i in range(len(X)):
      print(file_list[i])
      str_src = str(os.path.split(file_list[i])[-1]).split('.')[0].split('_')[-1]
      print(out[i])
      str_out = ''.join([str(x) for x in out[i] if x != -1])
      print(str_src, str_out)
      if str_src != str_out:
        error_count += 1
        print('################################', error_count)
      # img = cv2.imread(file_list[i])
      # cv2.imshow('image', img)
      # cv2.waitKey()


  class LossHistory(Callback):
    def on_train_begin(self, logs={}):
      self.losses = []

    def on_epoch_end(self, epoch, logs=None):
      model.save_weights('model_1018.w')
      base_model.save_weights('base_model_1018.w')
      test(base_model)

    def on_batch_end(self, batch, logs={}):
      self.losses.append(logs.get('loss'))


  # checkpointer = ModelCheckpoint(filepath="keras_seq2seq_1018.hdf5", verbose=1, save_best_only=True, )
  history = LossHistory()

  # base_model.load_weights('base_model_1018.w')
  # model.load_weights('model_1018.w')

  X, Y = gen_image_data()
  maxin = 4900
  subseq_size = 100
  batch_size = 10
  result = model.fit([X[:maxin], Y[:maxin], np.array(np.ones(len(X)) * int(conv_shape[1]))[:maxin],
                      np.array(np.ones(len(X)) * seq_len)[:maxin]], Y[:maxin],
                     batch_size=20,
                     epochs=1000,
                     callbacks=[history, plotter, EarlyStopping(patience=10)],  # checkpointer, history,
                     validation_data=([X[maxin:], Y[maxin:], np.array(np.ones(len(X)) * int(conv_shape[1]))[maxin:],
                                       np.array(np.ones(len(X)) * seq_len)[maxin:]], Y[maxin:]),
                     )

  test(base_model)

  K.clear_session()
